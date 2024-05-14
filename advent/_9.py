from pyteal import *
from beaker import *
from beaker.decorators import *
from beaker.consts import TRUE

from .base import Base
from .utils import (
    AbsDiff,
    BoxScratchStore,
    Max,
    Min,
    Nop,
    SScratchVar,
    BoxAllocator,
    BoxArray,
    Forever,
)

MAX_SPAN = 400


class Solution(Base):
    work_bytes = ReservedAccountStateValue(TealType.bytes, max_keys=1)

    def work_box_size(self):
        return MAX_SPAN * (MAX_SPAN // 8 + 1) + 8 * (8 + 9 + 9)

    def flush(self, state: dict, cached):
        return Seq(self.save_work(state), Seq([x.flush() for x in cached]))

    @internal(TealType.uint64)
    def solve_impl(self):
        state = dict(
            work_box=(work_box := SScratchVar(TealType.bytes)),
        )
        alloc = BoxAllocator(work_box.load())
        scratch = BoxScratchStore(
            alloc,
            phase := SScratchVar(TealType.uint64),
            cX := SScratchVar(TealType.uint64),
            cY := SScratchVar(TealType.uint64),
            minX := SScratchVar(TealType.uint64),
            maxX := SScratchVar(TealType.uint64),
            minY := SScratchVar(TealType.uint64),
            maxY := SScratchVar(TealType.uint64),
            unique := SScratchVar(TealType.uint64),
            *(tX := [SScratchVar(TealType.uint64) for _ in range(9)]),
            *(tY := [SScratchVar(TealType.uint64) for _ in range(9)]),
        )
        mask = BoxArray(alloc, MAX_SPAN // 8 + 1, MAX_SPAN)
        cached = [scratch]

        midpoint = 2**32

        op = SScratchVar(TealType.bytes)
        amt = SScratchVar(TealType.uint64)

        MaskReset = For((i := SScratchVar()).store(0), i < MAX_SPAN, i.inc()).Do(
            mask[i].set(b"\0" * mask.element_size)
        )
        MaskSet = lambda x, y: Seq(
            (tmpY := SScratchVar()).store(y - minY),
            mask[tmpY].set(SetBit(mask[tmpY].get(), x - minX, Int(1))),
        )
        MaskGet = lambda x, y: Seq(GetBit(mask[y - minY].get(), x - minX))

        Move = lambda x: Seq(
            If(op == "L")
            .Then(cX.dec(x))
            .ElseIf(op == "R")
            .Then(cX.inc(x))
            .ElseIf(op == "U")
            .Then(cY.dec(x))
            .ElseIf(op == "D")
            .Then(cY.inc(x)),
        )
        Follow = lambda sX, sY, dX, dY: Seq(
            (deltaX := SScratchVar()).store(AbsDiff(sX.load(), dX.load())),
            (deltaY := SScratchVar()).store(AbsDiff(sY.load(), dY.load())),
            If(And(deltaX < 2, deltaY < 2)).Then(Continue()),
            If(deltaX == 0)
            .Then(If(sY > dY).Then(dY.inc()).Else(dY.dec()))
            .ElseIf(deltaY == 0)
            .Then(If(sX > dX).Then(dX.inc()).Else(dX.dec()))
            .ElseIf(And(sX > dX, sY > dY))
            .Then(dX.inc(), dY.inc())
            .ElseIf(And(sX > dX, sY < dY))
            .Then(dX.inc(), dY.dec())
            .ElseIf(And(sX < dX, sY > dY))
            .Then(dX.dec(), dY.inc())
            .ElseIf(And(sX < dX, sY < dY))
            .Then(dX.dec(), dY.dec()),
        )

        @Subroutine(TealType.none)
        def FindBounds():
            return Seq(
                If(self.reader_done()).Then(
                    Assert(maxX - minX < Int(MAX_SPAN), comment="X span is too large"),
                    Assert(maxY - minY < Int(MAX_SPAN), comment="Y span is too large"),
                    cX.store(midpoint),
                    cY.store(midpoint),
                    tX[0].store(cX),
                    tY[0].store(cY),
                    MaskSet(tX[0], tY[0]),
                    unique.store(1),
                    phase.inc(),
                    self.reader_seek(0),
                    Return(),
                ),
                op.store(self.reader_next(Int(1))),
                self.reader_index().inc(),
                Assert(self.reader_next_uint(amt)),
                Move(amt),
                minX.store(Min(minX.load(), cX.load())),
                maxX.store(Max(maxX.load(), cX.load())),
                minY.store(Min(minY.load(), cY.load())),
                maxY.store(Max(maxY.load(), cY.load())),
            )

        @Subroutine(TealType.none)
        def Simulate():
            return Seq(
                If(self.reader_done()).Then(
                    self.set_solution(part_one=unique),
                    cX.store(midpoint),
                    cY.store(midpoint),
                    Seq([x.store(cX) for x in tX]),
                    Seq([x.store(cY) for x in tY]),
                    MaskReset,
                    MaskSet(tX[-1], tY[-1]),
                    unique.store(1),
                    phase.inc(),
                    self.reader_seek(0),
                    Return(),
                ),
                op.store(self.reader_next(Int(1))),
                self.reader_index().inc(),
                Assert(self.reader_next_uint(amt)),
                For((i := SScratchVar()).store(0), i < amt, i.inc()).Do(
                    Move(1),
                    Follow(cX, cY, tX[0], tY[0]),
                    If(Not(MaskGet(tX[0], tY[0]))).Then(
                        MaskSet(tX[0], tY[0]), unique.inc()
                    ),
                ),
            )

        @Subroutine(TealType.none)
        def Simulate10():
            return Seq(
                If(self.reader_done()).Then(
                    phase.inc(),
                    self.set_solution(part_two=unique),
                    Return(),
                ),
                op.store(self.reader_next(Int(1))),
                self.reader_index().inc(),
                Assert(self.reader_next_uint(amt)),
                For((i := SScratchVar()).store(0), i < amt, i.inc()).Do(
                    Move(1),
                    Follow(cX, cY, tX[0], tY[0]),
                    Seq([Follow(tX[i], tY[i], tX[i + 1], tY[i + 1]) for i in range(8)]),
                    If(Not(MaskGet(tX[-1], tY[-1]))).Then(
                        MaskSet(tX[-1], tY[-1]), unique.inc()
                    ),
                ),
            )

        return Seq(
            amt.store(0),
            self.init_state(state),
            self.load_work(state),
            If(work_box == "")
            .Then(
                work_box.store(self.work_box()),
                Seq([x.cache() for x in cached]),
                cX.store(midpoint),
                cY.store(midpoint),
                minX.store(cX),
                maxX.store(cX),
                minY.store(cY),
                maxY.store(cY),
                MaskReset,
            )
            .Else(Seq([x.cache() for x in cached])),
            #
            Forever().Do(
                self.check_low_budget(self.flush(state, cached), 15),
                If(phase == 0)
                .Then(FindBounds())
                .ElseIf(phase == 1)
                .Then(Simulate())
                .ElseIf(phase == 2)
                .Then(Simulate10())
                .Else(Break()),
                Nop(),
            ),
            self.flush(state, cached),
            Return(TRUE),
        )
