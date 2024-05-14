from dataclasses import dataclass
from typing import Callable, Generic, Optional, TypeVar, Union, get_args
from algosdk.constants import MICROALGOS_TO_ALGOS_RATIO
from pyteal import *
from pyteal.ast.seq import _use_seq_if_multiple
from pyteal.types import require_type
import operator
import sys

from .third_party.account import Account

# TODO: uncomment to use a specific account
# from .secrets import user_pk  # type: ignore
user_pk = None


DEBUG = False


def fmt_algo(amount):
    return f"{amount / MICROALGOS_TO_ALGOS_RATIO:.6f}Ⱥ"


def solver_user(algod_client):
    if user_pk is None:
        return Account.create(algod_client=algod_client)
    else:
        return Account(private_key=user_pk, algod_client=algod_client)


def more_juice(rec_limit=2000):
    sys.setrecursionlimit(rec_limit)  # Need more juice


Wrappable = Union[int, str, bytes, ScratchVar, Expr, "BoxSlot"]


def wrap(value: Wrappable):
    if isinstance(value, int):
        return Int(value)
    if isinstance(value, str) or isinstance(value, bytes):
        return Bytes(value)
    if isinstance(value, ScratchVar):
        return value.load()
    if isinstance(value, BoxSlot):
        return value.get()
    return value


class WSubroutine:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs

    def __call__(self, fn):
        sub = Subroutine(*self.args, **self.kwargs)(fn)

        def wrapped(*args):
            return sub(*map(wrap, args))

        return wrapped


def SScratchVarWrap(fn):
    def new_fn(self, other):
        return self._op(other, getattr(operator, fn.__name__))

    return new_fn


class SScratchVar(ScratchVar):
    def store(self, value: Wrappable) -> Expr:
        return super().store(wrap(value))

    def concat(self, value: Wrappable) -> Expr:
        return self.store(Concat(self.load(), wrap(value)))

    def inc(self, other=1):
        return self.store(self.load() + wrap(other))

    def dec(self, other=1):
        return self.store(self.load() - wrap(other))

    def itoa(self):
        return itoa(self.load())

    def _op(self, other, op):
        return op(self.load(), wrap(other))

    @SScratchVarWrap
    def __lt__(self, other):
        ...

    @SScratchVarWrap
    def __le__(self, other):
        ...

    @SScratchVarWrap
    def __gt__(self, other):
        ...

    @SScratchVarWrap
    def __ge__(self, other):
        ...

    @SScratchVarWrap
    def __eq__(self, other):
        ...

    @SScratchVarWrap
    def __ne__(self, other):
        ...

    @SScratchVarWrap
    def __add__(self, other):
        ...

    @SScratchVarWrap
    def __sub__(self, other):
        ...

    @SScratchVarWrap
    def __mod__(self, other):
        ...

    @SScratchVarWrap
    def __mul__(self, other):
        ...

    @SScratchVarWrap
    def __truediv__(self, other):
        ...


@WSubroutine(TealType.uint64)
def digit_to_int(digit: Expr):
    return GetByte(digit, Int(0)) - Int(ord("0"))


@WSubroutine(TealType.uint64)
def atoi(s: Expr):
    return Seq(
        (ret := ScratchVar()).store(Int(0)),
        For(
            (i := ScratchVar()).store(Int(0)),
            i.load() < Len(s),
            i.store(i.load() + Int(1)),
        ).Do(
            ret.store(ret.load() * Int(10) + (GetByte(s, i.load()) - Int(ord("0")))),
        ),
        ret.load(),
    )


@Subroutine(TealType.uint64)
def atoish(s: Expr, index: ScratchVar):
    return Seq(
        (ret := SScratchVar()).store(0),
        For(
            Seq(),
            And(
                index.load() < Len(s),
                Seq(
                    (c := SScratchVar()).store(GetByte(s, index.load())),
                    And(c >= ord("0"), c <= ord("9")),
                ),
            ),
            index.store(index.load() + Int(1)),
        ).Do(
            ret.store(ret * 10 + (c - ord("0"))),
        ),
        ret.load(),
    )


@WSubroutine(TealType.bytes)
def itoa(num: Expr):
    return Seq(
        If(Not(num)).Then(Return(Bytes("0"))),
        (ret := SScratchVar()).store(""),
        (n := SScratchVar()).store(num),
        While(n.load()).Do(
            ret.store(
                Concat(SetByte(Bytes("\0"), Int(0), n % 10 + Int(ord("0"))), ret.load())
            ),
            n.store(n / 10),
        ),
        Return(ret.load()),
    )


def _SLogWrap(x):
    x = wrap(x)
    if x.type_of() == TealType.uint64:
        x = itoa(x)
    return x


def SLog(*args):
    if len(args) == 1:
        return Log(_SLogWrap(args[0]))
    return Log(Concat(*[y for x in args for y in [_SLogWrap(x), _SLogWrap(" ")]][:-1]))


@Subroutine(TealType.none)
def Swap(a: ScratchVar, b: ScratchVar):
    return Seq(
        (c := ScratchVar()).store(a.load()),
        a.store(b.load()),
        b.store(c.load()),
    )


def Nop():
    return Pop(Int(0))


@WSubroutine(TealType.uint64)
def Min(a: Expr, b: Expr):
    return If(a <= b).Then(a).Else(b)


@WSubroutine(TealType.uint64)
def Max(a: Expr, b: Expr):
    return If(a >= b).Then(a).Else(b)


@WSubroutine(TealType.uint64)
def AbsDiff(a: Expr, b: Expr):
    return If(a >= b).Then(a - b).Else(b - a)


@Subroutine(TealType.uint64)
def Findi(buffer: ScratchVar, target: Expr):
    return Seq(
        (len := ScratchVar()).store(Len(buffer.load())),
        For((i := SScratchVar()).store(0), i < len, i.inc()).Do(
            If(target == GetByte(buffer.load(), i.load())).Then(Break())
        ),
        Return(i.load()),
    )


class Bitmask:
    # NOTE: ops are inline since are all pretty short
    def __init__(self, size):
        self.size = size
        self.intmask = size <= 64
        self.scratch = SScratchVar(TealType.uint64 if self.intmask else TealType.bytes)

    def create(self):
        return self.store(0 if self.intmask else b"\0" * (self.size // 8 + 1))

    def store(self, value: Expr):
        return self.scratch.store(value)

    def set(self, i: Expr):
        return self.scratch.store(SetBit(self.scratch.load(), i, Int(1)))

    def get(self, i: Expr):
        return GetBit(self.scratch.load(), i)

    def __or__(self, other: "Bitmask"):
        assert self.size == other.size
        if self.intmask:
            return self.scratch.load() | other.scratch.load()
        else:
            return BytesOr(self.scratch.load(), other.scratch.load())


class Forever(Expr):
    """Slightly optimized While(True)"""

    def __init__(self) -> None:
        super().__init__()
        self.doBlock: Optional[Expr] = None

    def __teal__(self, options: "CompileOptions"):
        if self.doBlock is None:
            raise TealCompileError("Forever expression must have a doBlock", self)

        options.enterLoop()

        doStart, doEnd = self.doBlock.__teal__(options)
        end = TealSimpleBlock([])

        doEnd.setNextBlock(doStart)
        breakBlocks, continueBlocks = options.exitLoop()

        for block in breakBlocks:
            block.setNextBlock(end)

        for block in continueBlocks:
            block.setNextBlock(doStart)

        return doStart, end

    def __str__(self):
        if self.doBlock is None:
            raise TealCompileError("Forever expression must have a doBlock", self)

        return "(Forever {})".format(self.doBlock)

    def type_of(self):
        if self.doBlock is None:
            raise TealCompileError("Forever expression must have a doBlock", self)
        return TealType.none

    def has_return(self):
        return False

    def Do(self, doBlock: Expr, *do_block_multi: Expr):
        if self.doBlock is not None:
            raise TealCompileError("Forever expression already has a doBlock", self)

        doBlock = _use_seq_if_multiple(doBlock, *do_block_multi)

        require_type(doBlock, TealType.none)
        self.doBlock = doBlock
        return self


def AndShort(*args: Expr):
    if len(args) == 1:
        return args[0]
    return If(args[0]).Then(AndShort(*args[1:])).Else(Int(0))


class BoxArea:
    def __init__(self, box_name: Wrappable, start: Wrappable, size: Wrappable):
        self.box_name = box_name
        self.start = start
        self.size = size
        self.cached = None
        self.direct_access = 0

    def extract(self, start: Wrappable, length: Wrappable, *, force_thru: bool = False):
        ret = []
        if DEBUG:
            ret.extend(
                [
                    (tmp_start := SScratchVar()).store(start),
                    (tmp_length := SScratchVar()).store(length),
                    Assert(tmp_length >= 0, comment="length must be positive"),
                    Assert(
                        tmp_start + tmp_length <= wrap(self.size),
                        comment="End out of bound",
                    ),
                ]
            )
            start = tmp_start
            length = tmp_length

        if self.cached is None:
            self.direct_access += 1

        if self.cached and not force_thru:
            ret.append(Extract(self.cached.load(), wrap(start), wrap(length)))
        else:
            ret.append(
                App.box_extract(
                    wrap(self.box_name), wrap(self.start) + wrap(start), wrap(length)
                )
            )
        return Seq(ret)

    def replace(self, start: Wrappable, value: Wrappable, *, force_thru: bool = False):
        ret = []
        if DEBUG:
            ret.extend(
                [
                    (tmp_start := SScratchVar()).store(start),
                    (tmp_value := SScratchVar()).store(value),
                    Assert(
                        tmp_start + Len(tmp_value.load()) <= wrap(self.size),
                        comment="Value overflow",
                    ),
                ]
            )
            start = tmp_start
            value = tmp_value

        if self.cached is None:
            self.direct_access += 1

        if self.cached and not force_thru:
            ret.append(
                self.cached.store(Replace(self.cached.load(), wrap(start), wrap(value)))
            )
        else:
            ret.append(
                App.box_replace(
                    wrap(self.box_name), wrap(self.start) + wrap(start), wrap(value)
                )
            )
        return Seq(ret)

    def copy(self, src: "BoxArea"):
        return self.replace(0, src.extract(0, src.size))

    def cache(self, skip_access_check=False):
        if not self.cached:
            self.cached = SScratchVar()
            if self.direct_access and not skip_access_check:
                raise ValueError(
                    f"Caching after {self.direct_access} direct accesses returned, this may cause inconsistencies"
                )
        return self.cached.store(self.extract(0, self.size, force_thru=True))

    def flush(self):
        return self.replace(0, self.cached, force_thru=True)


class BoxAllocator:
    def __init__(self, box_name: Wrappable):
        self.box_name = box_name
        self.index = 0

    def alloc(self, size: int) -> BoxArea:
        area = BoxArea(self.box_name, self.index, size)
        self.index += size
        return area


class BoxSlot:
    def __init__(self, area: BoxArea, start: Wrappable, length: Wrappable):
        self.area = area
        self.start = start
        self.length = length

    def get(self):
        return self.area.extract(self.start, self.length)

    def set(self, value: Wrappable):
        if DEBUG:
            return Seq(
                (tmp := SScratchVar()).store(value),
                Assert(
                    Len(tmp.load()) == wrap(self.length),
                    comment="Buffer write mismatch",
                ),
                self.area.replace(self.start, tmp.load()),
            )
        return self.area.replace(self.start, value)


def BoxSlotCustom(encode, decode):
    class _BoxSlot(BoxSlot):
        def get(self):
            return decode(super().get())

        def set(self, value: Wrappable):
            return super().set(encode(wrap(value)))

    return _BoxSlot


BoxSlotUint = BoxSlotCustom(Itob, Btoi)


@dataclass
class BoxSlotStructEntry:
    start: int
    length: int
    slot_cls: type


_U = TypeVar("_U")


class BoxSlotStruct(BoxSlot, Generic[_U]):
    __slot_struct__ = None

    def __getattr__(self, name: str) -> BoxSlot | BoxSlotUint:
        self._require_struct()
        if name not in self.__slot_struct__:
            raise AttributeError(f"Cannot find struct field {name}")
        slot = self.__slot_struct__[name]
        return slot.slot_cls(self.area, self.start + wrap(slot.start), slot.length)

    @classmethod
    def _size(cls, struct_cls):
        return sum(x.length for x in cls._compute_struct(struct_cls).values())

    @classmethod
    def _compute_struct(cls, struct_cls) -> dict[str, BoxSlotStructEntry]:
        start = 0
        ret = {}
        for field in struct_cls.__dict__:
            if field.startswith("__"):
                continue
            tp = getattr(struct_cls, field)
            if field in ("area", "start", "length"):
                raise ValueError(
                    f"Struct field `{field}` of `{struct_cls}` shadows a slot element and cannot be used."
                )
            if tp == Int:
                slot = BoxSlotStructEntry(start, 8, BoxSlotUint)
            elif tp[0] == Bytes:
                slot = BoxSlotStructEntry(start, tp[1], BoxSlot)
            else:
                raise ValueError(f"Unkown field type for {struct_cls}.{field}")
            ret[field] = slot
            start += slot.length
        return ret

    def _require_struct(self):
        if self.__slot_struct__ is not None:
            return
        self.__slot_struct__ = self._compute_struct(get_args(self.__orig_class__)[0])


_T = TypeVar("_T")


class BoxArrayBase(Generic[_T]):
    def __init__(
        self,
        allocator: BoxAllocator,
        element_size: int,
        capacity: int,
        slot_cls=BoxSlot,
    ):
        self.area = allocator.alloc(element_size * capacity)
        self.element_size = element_size
        self.capacity = capacity
        self.slot_cls = slot_cls

    def _index(self, index: Wrappable):
        if DEBUG:
            return Seq(
                (tmp := SScratchVar()).store(index),
                Assert(tmp < self.capacity, comment="Overflowed array capacity"),
                tmp * self.element_size,
            )
        return wrap(index) * wrap(self.element_size)

    def __getitem__(self, index: Wrappable) -> _T:
        return self.slot_cls(self.area, self._index(index), self.element_size)

    def cache(self):
        return self.area.cache()

    def flush(self):
        return self.area.flush()


class BoxArray(BoxArrayBase[BoxSlot]):
    ...


class BoxArrayUint(BoxArrayBase[BoxSlotUint]):
    def __init__(self, allocator: BoxAllocator, capacity: int):
        super().__init__(allocator, 8, capacity, slot_cls=BoxSlotUint)


class BoxArrayCustom(BoxArray):
    def __init__(
        self, allocator: BoxAllocator, element_size: int, capacity: int, enc_fn, dec_fn
    ):
        super().__init__(
            allocator, element_size, capacity, slot_cls=BoxSlotCustom(enc_fn, dec_fn)
        )


class BoxArrayStruct(BoxArrayBase[BoxSlotStruct[_T]], Generic[_T]):
    def __init__(self, allocator: BoxAllocator, cls: type, capacity: int):
        super().__init__(
            allocator,
            BoxArrayStruct.element_size(cls),
            capacity,
            slot_cls=BoxSlotStruct[cls],
        )

    @staticmethod
    def element_size(cls):
        return BoxSlotStruct._size(cls)


class BoxScratchStore:
    def __init__(
        self, allocator: BoxAllocator, *args: ScratchVar | tuple[ScratchVar, int]
    ):
        size = 0
        for arg in args:
            if isinstance(arg, tuple):
                if arg[0].storage_type() != TealType.bytes or not isinstance(
                    arg[1], int
                ):
                    raise NotImplementedError(
                        f"BoxScratchStore tuple is reserved for byte scratchvars and capacity"
                    )
                else:
                    size += arg[1]
                    continue

            if arg.storage_type() != TealType.uint64:
                raise NotImplementedError(
                    f"BoxScratchStore doesn't support {arg.storage_type} scratchvar"
                )
            else:
                size += 8

        self.area = allocator.alloc(size)
        self.args = []
        self.slots = []
        start = 0
        for arg in args:
            if isinstance(arg, tuple):
                self.args.append(arg[0])
                self.slots.append(BoxSlot(self.area, start, arg[1]))
            else:
                self.args.append(arg)
                self.slots.append(BoxSlotUint(self.area, start, 8))
            start += self.slots[-1].length

    def init(self):
        return Seq(
            [
                arg.store(Int(0) if arg.type == TealType.uint64 else Bytes(""))
                for arg in self.args
            ]
        )

    def cache(self, cache_area=True):
        return Seq(
            self.area.cache() if cache_area else Seq(),
            Seq([arg.store(slot.get()) for arg, slot in zip(self.args, self.slots)]),
        )

    def flush(self, flush_area=True):
        return Seq(
            Seq([slot.set(arg.load()) for arg, slot in zip(self.args, self.slots)]),
            self.area.flush() if flush_area else Seq(),
        )


def Sort(array: BoxArrayBase, size: Wrappable, cmp: Callable[[BoxSlot, BoxSlot], Expr]):
    return Seq(
        (swap := SScratchVar(TealType.uint64)).store(1),
        (ub := SScratchVar(TealType.uint64)).store(size),
        While(swap.load()).Do(
            swap.store(0),
            For((i := SScratchVar()).store(1), i < ub, i.inc()).Do(
                If(cmp(array[i], array[i - 1])).Then(
                    (tmp := SScratchVar()).store(array[i].get()),
                    array[i].set(array[i - 1].get()),
                    array[i - 1].set(tmp),
                    swap.inc(),
                )
            ),
        ),
    )
