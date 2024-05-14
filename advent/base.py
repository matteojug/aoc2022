import re
from types import SimpleNamespace

from pyteal import *
from beaker import *
from beaker.decorators import *
from beaker.consts import TRUE, FALSE

from algosdk.constants import MIN_TXN_FEE

from .utils import SScratchVar, Min, Findi, wrap, Wrappable, Forever, Max, SLog


class SolveStatus(abi.NamedTuple):
    done: abi.Field[abi.Bool]
    iter_cost: abi.Field[abi.Uint64]


DEFAULT_MEASUREMENT = "default"


class Base(Application):
    TEAL_VERSION = 8
    READER_LINE_UNROLL = 10

    name: Final[ApplicationStateValue] = ApplicationStateValue(
        stack_type=TealType.bytes,
    )

    user_addr32: Final[AccountStateValue] = AccountStateValue(
        stack_type=TealType.bytes,
    )
    locked_funds: Final[AccountStateValue] = AccountStateValue(
        stack_type=TealType.uint64
    )
    input_size: Final[AccountStateValue] = AccountStateValue(
        stack_type=TealType.uint64,
    )
    writer_index: Final[AccountStateValue] = AccountStateValue(
        stack_type=TealType.uint64,
    )
    # Don't use this directly
    _reader_index: Final[AccountStateValue] = AccountStateValue(
        stack_type=TealType.uint64
    )

    part_one: AccountStateValue = AccountStateValue(
        stack_type=TealType.uint64,
    )
    part_two: AccountStateValue = AccountStateValue(
        stack_type=TealType.uint64,
    )

    work_ints = SimpleNamespace(max_keys=0)
    work_bytes = SimpleNamespace(max_keys=0)

    def __init__(self, test=False):
        self.measurements = {}
        self.measure_init(DEFAULT_MEASUREMENT, TealType.uint64)
        self.is_test = test
        super().__init__(self.TEAL_VERSION)

    @create
    def create(self):
        day = re.match(r"^.+\._(\d+)", self.__module__).group(1)
        return self.name.set(Bytes(f"advent-of-code-22/day-{day}"))

    @update(authorize=Authorize.only(Global.creator_address()))
    def update(self):
        return Approve()

    @delete(authorize=Authorize.only(Global.creator_address()))
    def delete(self):
        return Approve()

    def measure_init(self, key, tp):
        self.measurements[key] = SScratchVar(tp)

    def work_key(self, key):
        return f"_{key}"

    def save_work(self, _kwargs=None, **kwargs: ScratchVar):
        if _kwargs is not None:
            assert not kwargs
            kwargs = _kwargs

        assert len(kwargs) <= self.work_ints.max_keys + self.work_bytes.max_keys
        return Seq(
            [
                App.localPut(Txn.sender(), Bytes(self.work_key(key)), value.load())
                for key, value in kwargs.items()
            ]
        )

    def load_work(self, _kwargs=None, **kwargs: ScratchVar):
        if _kwargs is not None:
            assert not kwargs
            kwargs = _kwargs

        assert len(kwargs) <= self.work_ints.max_keys + self.work_bytes.max_keys
        return Seq(
            [
                Seq(
                    (
                        stored := App.localGetEx(
                            Txn.sender(),
                            Global.current_application_id(),
                            Bytes(self.work_key(key)),
                        )
                    ),
                    If(stored.hasValue()).Then(
                        value.store(stored.value()),
                        App.localDel(Txn.sender(), Bytes(self.work_key(key))),
                    ),
                )
                for key, value in kwargs.items()
            ]
        )

    def init_state(self, state, **kwargs):
        return Seq(
            [
                v.store(
                    kwargs.get(k, Int(0) if v.type == TealType.uint64 else Bytes(""))
                )
                for k, v in state.items()
            ]
        )

    def check_low_budget(
        self,
        state: dict | Expr,
        base_budget_multiplier: int = 1,
        budget: Optional[int] = None,
    ):
        return If(
            Global.opcode_budget()
            < Int(
                base_budget_multiplier * consts.APP_CALL_BUDGET
                if budget is None
                else budget
            )
        ).Then(
            self.save_work(state) if isinstance(state, dict) else state,
            Return(FALSE),
        )

    def set_solution(self, part_one: Wrappable = None, part_two: Wrappable = None):
        seq = []
        if part_one is not None:
            seq.append(self.part_one.set(wrap(part_one)))
        if part_two is not None:
            seq.append(self.part_two.set(wrap(part_two)))
        return Seq(seq)

    @external
    def get_solution(self, *, output: abi.Tuple2[abi.Uint64, abi.Uint64]):
        return Seq(
            (part_one := abi.Uint64()).set(self.part_one.get()),
            (part_two := abi.Uint64()).set(self.part_two.get()),
            output.set(part_one, part_two),
        )

    @internal(TealType.bytes)
    def input_box(self):
        return Concat(self.user_addr32.get(), Bytes(":input"))

    @internal(TealType.bytes)
    def work_box(self):
        return Concat(self.user_addr32.get(), Bytes(":work"))

    def work_box_size(self):
        return None

    @internal(TealType.uint64)
    def box_cost(self, size: Expr):
        return Int(2500) + Int(400) * (Int(64) + size)

    @internal(TealType.uint64)
    def box_funds(self):
        ret = self.box_cost(self.input_size.get())
        if (work := self.work_box_size()) is not None:
            ret = ret + self.box_cost(wrap(work))
        return ret

    @internal(TealType.none)
    def init_box(self):
        ret = [
            Assert(self.locked_funds.get()),
            self.writer_index.set(Int(0)),
            Pop(App.box_create(self.input_box(), self.input_size.get())),
        ]
        if (work := self.work_box_size()) is not None:
            ret.append(Pop(App.box_create(self.work_box(), wrap(work))))
        return Seq(ret)

    @opt_in
    def opt_in(
        self,
        sender_addr: abi.String,
        input_size: abi.Uint64,
        *,
        output: abi.Uint64,
    ):
        return Seq(
            self.user_addr32.set(sender_addr.get()),
            self.input_size.set(input_size.get()),
            self.locked_funds.set(Int(0)),
            output.set(self.box_funds()),
        )

    @external
    def deposit(self, txn: abi.PaymentTransaction):
        return Seq(
            Assert(txn.get().type_enum() == TxnType.Payment),
            Assert(txn.get().receiver() == self.address),
            Assert(txn.get().amount() == self.box_funds()),
            self.locked_funds.set(txn.get().amount()),
        )

    @external(read_only=True)
    def get_boxes(
        self, *, output: abi.Tuple2[abi.DynamicArray[abi.String], abi.Uint64]
    ):
        ret = [(box := abi.String()).set(self.input_box())]
        boxes = [box]
        budget = self.input_size.get()
        if (work := self.work_box_size()) is not None:
            ret.append((box2 := abi.String()).set(self.work_box()))
            boxes.append(box2)
            budget = budget + wrap(work)
        return Seq(
            *ret,
            (boxes_abi := abi.make(abi.DynamicArray[abi.String])).set(boxes),
            (budget_abi := abi.Uint64()).set(budget),
            output.set(boxes_abi, budget_abi),
        )

    @external
    def input_append(self, chunk: abi.String, *, output: abi.Uint64):
        return Seq(
            If(Not(self.writer_index.exists())).Then(self.init_box()),
            (chunk_var := ScratchVar()).store(chunk.get()),
            App.box_replace(
                self.input_box(), self.writer_index.get(), chunk_var.load()
            ),
            self.writer_index.increment(Len(chunk_var.load())),
            output.set(self.writer_index.get()),
        )

    @external
    def input_clear(self, *, output: abi.Uint64):
        return Seq(
            self.reader_seek(Int(0), no_cache=True),
            Assert(
                App.box_delete(self.input_box()), comment="Input box does not exists"
            ),
            Assert(App.box_delete(self.work_box()), comment="Work box does not exists")
            if self.work_box_size() is not None
            else Seq(),
            self.writer_index.delete(),
            self.input_size.delete(),
            InnerTxnBuilder.Execute(
                {
                    TxnField.type_enum: TxnType.Payment,
                    TxnField.receiver: Txn.sender(),
                    TxnField.amount: self.locked_funds.get(),
                    TxnField.fee: Int(0),
                }
            ),
            output.set(self.locked_funds.get()),
            self.locked_funds.set(Int(0)),
        )

    def reader_index(self):
        return self._cache_reader_index

    def reader_remaining(self):
        return self._cache_input_size.load() - self.reader_index().load()

    def reader_seek(self, read_index, no_cache=False):
        if no_cache:
            return self._reader_index.set(wrap(read_index))
        return self.reader_index().store(read_index)

    def reader_done(self):
        return self.reader_index().load() == self._cache_input_size.load()

    def reader_available(self):
        return self.reader_index().load() < self._cache_input_size.load()

    def reader_skip(self, count):
        return self.reader_index().inc(count)

    @internal(TealType.bytes)
    def reader_next(self, size: Expr):
        return Seq(
            (ret := ScratchVar()).store(
                App.box_extract(
                    self._cache_box.load(), self.reader_index().load(), size
                )
            ),
            self.reader_index().inc(size),
            ret.load(),
        )

    @internal(TealType.bytes)
    def reader_get(self, start: Expr, size: Expr):
        return Seq(
            (ret := ScratchVar()).store(
                App.box_extract(self._cache_box.load(), start, size)
            ),
            ret.load(),
        )

    @internal(TealType.bytes)
    def reader_next_line(self):
        # NOTE: trims the endline char
        ret = ScratchVar(TealType.bytes)
        return Seq(
            If(self.reader_remaining() >= Int(self.READER_LINE_UNROLL))
            .Then(
                ret.store(
                    App.box_extract(
                        self._cache_box.load(),
                        self.reader_index().load(),
                        Int(self.READER_LINE_UNROLL),
                    )
                ),
                Seq(
                    [
                        If(Extract(ret.load(), Int(i), Int(1)) == Bytes("\n")).Then(
                            self.reader_index().inc(i + 1),
                            Return(
                                Extract(ret.load(), Int(0), Int(i)) if i else Bytes("")
                            ),
                        )
                        for i in range(self.READER_LINE_UNROLL)
                    ]
                ),
                self.reader_index().inc(self.READER_LINE_UNROLL),
            )
            .Else(ret.store(Bytes(""))),
            Forever().Do(
                (c := SScratchVar(TealType.bytes)).store(
                    App.box_extract(
                        self._cache_box.load(), self.reader_index().load(), Int(1)
                    )
                ),
                self.reader_index().inc(),
                If(c == "\n").Then(Break()),
                ret.store(Concat(ret.load(), c.load())),
            ),
            ret.load(),
        )

    @internal(TealType.bytes)
    def reader_next_line_long(self):
        # NOTE: trims the endline char
        return Seq(
            (ret := SScratchVar()).store(Bytes("")),
            Forever().Do(
                (buffer_size := SScratchVar()).store(
                    Min(
                        Int(4096),
                        self.reader_remaining(),
                    )
                ),
                (buffer := ScratchVar()).store(
                    App.box_extract(
                        self._cache_box.load(),
                        self.reader_index().load(),
                        buffer_size.load(),
                    )
                ),
                (new_line := SScratchVar()).store(Findi(buffer, Int(ord("\n")))),
                self.reader_index().inc(new_line),
                If(new_line < buffer_size).Then(
                    ret.concat(Substring(buffer.load(), Int(0), new_line.load())),
                    Break(),
                ),
                ret.concat(buffer),
            ),
            # Skip newline
            self.reader_index().inc(),
            ret.load(),
        )

    @internal(TealType.uint64)
    def reader_next_uint(self, output: ScratchVar):
        c = SScratchVar(TealType.uint64)
        next_char = Seq(
            c.store(
                GetByte(
                    App.box_extract(
                        self._cache_box.load(), self.reader_index().load(), Int(1)
                    ),
                    Int(0),
                )
            ),
            self.reader_index().inc(),
        )
        return Seq(
            next_char,
            If(Or(c < ord("0"), c > ord("9"))).Then(Return(FALSE)),
            output.store(c - ord("0")),
            Forever().Do(
                next_char,
                If(Or(c < ord("0"), c > ord("9"))).Then(Break()),
                output.store(output.load() * Int(10) + (c - ord("0"))),
            ),
            Return(TRUE),
        )

    @internal(TealType.uint64)
    def reader_next_int(self, output: ScratchVar, sign: ScratchVar):
        c = SScratchVar(TealType.uint64)
        next_char = Seq(
            c.store(
                GetByte(
                    App.box_extract(
                        self._cache_box.load(), self.reader_index().load(), Int(1)
                    ),
                    Int(0),
                )
            ),
            self.reader_index().inc(),
        )
        return Seq(
            sign.store(Int(0)),
            next_char,
            If(c == ord("-"))
            .Then(sign.store(Int(1)), output.store(Int(0)))
            .ElseIf(Or(c < ord("0"), c > ord("9")))
            .Then(Return(FALSE))
            .Else(output.store(c - ord("0"))),
            Forever().Do(
                next_char,
                If(Or(c < ord("0"), c > ord("9"))).Then(Break()),
                output.store(output.load() * Int(10) + (c - ord("0"))),
            ),
            Return(TRUE),
        )

    def measure_budget(self, *ops, key=DEFAULT_MEASUREMENT):
        return Seq(
            (tmp := SScratchVar(TealType.uint64)).store(Global.opcode_budget()),
            *ops,
            tmp.dec(Global.opcode_budget()),
            self.measurements[key].store(
                Max(self.measurements[key].load(), tmp.load())
            ),
        )

    @external
    def nop(self):
        return Seq()

    @external
    def solve(self, *, output: SolveStatus):
        self._cache_box = ScratchVar()
        self._cache_reader_index = SScratchVar()
        self._cache_input_size = ScratchVar()

        return Seq(
            OpUp(OpUpMode.OnCall).maximize_budget(
                Int(256 * MIN_TXN_FEE), OpUpFeeSource.GroupCredit
            ),
            (init_budget := ScratchVar(TealType.uint64)).store(Global.opcode_budget()),
            Seq([x.store(0) for x in self.measurements.values()]),
            self._cache_box.store(self.input_box()),
            self._cache_reader_index.store(self._reader_index.get()),
            self._cache_input_size.store(self.input_size.get()),
            (solved := abi.Bool()).set(self.solve_impl()),
            self._reader_index.set(self._cache_reader_index.load()),
            Seq(
                [
                    If(value.load()).Then(SLog(f"{key}:", value))
                    for key, value in self.measurements.items()
                ]
            ),
            (budget := abi.Uint64()).set(init_budget.load() - Global.opcode_budget()),
            output.set(solved, budget),
        )

    @internal(TealType.uint64)
    def solve_impl(self):
        raise NotImplementedError()
