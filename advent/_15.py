from pyteal import *
from beaker import *
from beaker.decorators import *
from beaker.consts import TRUE, FALSE

from .base import Base
from .utils import (
    AbsDiff,
    BoxArrayStruct,
    BoxScratchStore,
    Forever,
    Max,
    Min,
    Nop,
    SLog,
    Sort,
    SScratchVar,
    BoxAllocator,
    itoa,
)

MAX_S = 30


class Endpoint:
    pos = Int
    close = Bytes, 1


class Rhombus:
    cx = Int
    cy = Int
    r = Int


class Solution(Base):
    work_bytes = ReservedAccountStateValue(TealType.bytes, max_keys=1)

    def work_box_size(self):
        return (
            8 * 6
            + MAX_S * 2 * BoxArrayStruct.element_size(Endpoint)
            + MAX_S * BoxArrayStruct.element_size(Rhombus)
        )

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
            ans := SScratchVar(TealType.uint64),
            index := SScratchVar(TealType.uint64),
            index2 := SScratchVar(TealType.uint64),
            endpoints_size := SScratchVar(TealType.uint64),
            rhs_size := SScratchVar(TealType.uint64),
        )
        endpoints = BoxArrayStruct(alloc, Endpoint, MAX_S * 2)
        rhs = BoxArrayStruct(alloc, Rhombus, MAX_S)
        cached = [scratch, endpoints]

        MID = Int(2**62)
        LINE = Int(2**62 + (10 if self.is_test else 2000000))
        COORD_MIN = MID
        COORD_MAX = Int(2**62 + (20 if self.is_test else 4000000))

        def offset(x, sign):
            return If(sign.load()).Then(MID - x.load()).Else(MID + x.load())

        def endpoints_cmp(a, b):
            return (
                If(a.pos.get() < b.pos.get())
                .Then(TRUE)
                .ElseIf(a.pos.get() == b.pos.get())
                .Then(BytesLt(a.close.get(), b.close.get()))
                .Else(FALSE)
            )

        @Subroutine(TealType.uint64)
        def check_point(x: Expr, y: Expr):
            return Seq(
                If(And(Min(x, y) >= COORD_MIN, Max(x, y) <= COORD_MAX)).Then(
                    For((i := SScratchVar()).store(0), i < rhs_size, i.inc()).Do(
                        If(
                            AbsDiff(rhs[i].cx, x) + AbsDiff(rhs[i].cy, y)
                            <= rhs[i].r.get()
                        ).Then(
                            Return(Int(0)),
                        )
                    ),
                    self.set_solution(part_two=((x - MID) * Int(4000000) + (y - MID))),
                    Return(Int(1)),
                ),
                Return(Int(0)),
            )

        @Subroutine(TealType.uint64)
        def intersect_and_check(
            ltr_x_: Expr,
            ltr_y_: Expr,
            ltr_s_: Expr,
            rtl_x_: Expr,
            rtl_y_: Expr,
            rtl_s_: Expr,
        ):
            return Seq(
                (ltr_x := SScratchVar()).store(ltr_x_),
                (ltr_y := SScratchVar()).store(ltr_y_),
                (ltr_s := SScratchVar()).store(ltr_s_),
                (rtl_x := SScratchVar()).store(rtl_x_),
                (rtl_y := SScratchVar()).store(rtl_y_),
                (rtl_s := SScratchVar()).store(rtl_s_),
                If(ltr_y < rtl_y)
                .Then(
                    (tmp := SScratchVar()).store(rtl_y - ltr_y),
                    If(tmp > ltr_s).Then(Return(FALSE)),
                    ltr_y.inc(tmp),
                    ltr_x.inc(tmp),
                    ltr_s.dec(tmp),
                )
                .ElseIf(ltr_y > rtl_y)
                .Then(
                    (tmp := SScratchVar()).store(ltr_y - rtl_y),
                    If(tmp > rtl_s).Then(Return(FALSE)),
                    rtl_y.inc(tmp),
                    rtl_x.inc(tmp),
                    rtl_s.dec(tmp),
                ),
                If(ltr_x > rtl_x).Then(Return(FALSE)),
                (mid := SScratchVar()).store(rtl_x - ltr_x),
                If(mid % 2).Then(Return(FALSE)),
                mid.store(mid / 2),
                If(Min(ltr_s, rtl_s) < mid.load()).Then(Return(FALSE)),
                (x := SScratchVar()).store(ltr_x + mid),
                (y := SScratchVar()).store(ltr_y + mid),
                Return(
                    check_point(x + 1, y.load())
                    + check_point(x - 1, y.load())
                    + check_point(x.load(), y - 1)
                    + check_point(x.load(), y + 1)
                ),
            )

        return Seq(
            self.init_state(state),
            self.load_work(state),
            (sx := SScratchVar()).store(0),
            (sy := SScratchVar()).store(0),
            (bx := SScratchVar()).store(0),
            (by := SScratchVar()).store(0),
            (sign := SScratchVar()).store(0),
            If(work_box == "")
            .Then(
                work_box.store(self.work_box()),
                Seq([x.cache() for x in cached]),
                scratch.init(),
            )
            .Else(Seq([x.cache() for x in cached])),
            #
            Forever().Do(
                self.check_low_budget(self.flush(state, cached), 10),
                #
                If(phase == 0)
                .Then(
                    # Sensor at x=3658485, y=2855273: closest beacon is at x=4263070, y=2991690
                    self.reader_skip(12),
                    Assert(self.reader_next_int(sx, sign)),
                    sx.store(offset(sx, sign)),
                    #
                    self.reader_skip(3),
                    Assert(self.reader_next_int(sy, sign)),
                    sy.store(offset(sy, sign)),
                    #
                    self.reader_skip(24),
                    Assert(self.reader_next_int(bx, sign)),
                    bx.store(offset(bx, sign)),
                    #
                    self.reader_skip(3),
                    Assert(self.reader_next_int(by, sign)),
                    by.store(offset(by, sign)),
                    #
                    (dist := SScratchVar()).store(
                        AbsDiff(sx.load(), bx.load()) + AbsDiff(sy.load(), by.load())
                    ),
                    (dist_line := SScratchVar()).store(AbsDiff(sy.load(), LINE)),
                    If(dist_line <= dist).Then(
                        (r := SScratchVar()).store(dist - dist_line),
                        endpoints[endpoints_size].pos.set(sx - r),
                        endpoints[endpoints_size].close.set(b"\0"),
                        endpoints_size.inc(),
                        endpoints[endpoints_size].pos.set(sx + r),
                        endpoints[endpoints_size].close.set(b"\1"),
                        endpoints_size.inc(),
                    ),
                    rhs[rhs_size].cx.set(sx),
                    rhs[rhs_size].cy.set(sy),
                    rhs[rhs_size].r.set(dist),
                    rhs_size.inc(),
                    If(self.reader_done()).Then(index.store(0), phase.inc()),
                )
                .ElseIf(phase == 1)
                .Then(
                    self.check_low_budget(self.flush(state, cached), budget=50000),
                    Sort(endpoints, endpoints_size, endpoints_cmp),
                    (open := SScratchVar()).store(0),
                    (last := SScratchVar()).store(0),
                    For((i := SScratchVar()).store(0), i < endpoints_size, i.inc()).Do(
                        If(endpoints[i].close.get() == Bytes("\0"))
                        .Then(
                            If(open == 0).Then(last.store(endpoints[i].pos.get())),
                            open.inc(),
                        )
                        .Else(
                            open.dec(),
                            If(open == 0).Then(
                                ans.inc(endpoints[i].pos.get() - last.load())
                            ),
                        )
                    ),
                    phase.inc(),
                    index.store(0),
                    index2.store(0),
                    sign.store(0),
                )
                .ElseIf(phase == 2)
                .Then(
                    If(index == index2)
                    .Then(
                        (tmp := SScratchVar()).store(rhs[index].r.get() + Int(1)),
                        If(
                            check_point(
                                rhs[index].cx.get() + tmp.load(),
                                rhs[index].cy.get(),
                            )
                            + check_point(
                                rhs[index].cx.get() - tmp.load(),
                                rhs[index].cy.get(),
                            )
                            + check_point(
                                rhs[index].cx.get(),
                                rhs[index].cy.get() + tmp.load(),
                            )
                            + check_point(
                                rhs[index].cx.get(),
                                rhs[index].cy.get() - tmp.load(),
                            )
                        ).Then(phase.inc(), Continue()),
                    )
                    .Else(
                        If(
                            intersect_and_check(
                                rhs[index].cx.get(),
                                rhs[index].cy.get() - rhs[index].r.get(),
                                rhs[index].r.get(),
                                rhs[index2].cx.get(),
                                rhs[index2].cy.get() - rhs[index2].r.get(),
                                rhs[index2].r.get(),
                            )
                            + intersect_and_check(
                                rhs[index].cx.get(),
                                rhs[index].cy.get() - rhs[index].r.get(),
                                rhs[index].r.get(),
                                rhs[index2].cx.get() + rhs[index2].r.get(),
                                rhs[index2].cy.get(),
                                rhs[index2].r.get(),
                            )
                            + intersect_and_check(
                                rhs[index].cx.get() - rhs[index].r.get(),
                                rhs[index].cy.get(),
                                rhs[index].r.get(),
                                rhs[index2].cx.get(),
                                rhs[index2].cy.get() - rhs[index2].r.get(),
                                rhs[index2].r.get(),
                            )
                            + intersect_and_check(
                                rhs[index].cx.get() - rhs[index].r.get(),
                                rhs[index].cy.get(),
                                rhs[index].r.get(),
                                rhs[index2].cx.get() + rhs[index2].r.get(),
                                rhs[index2].cy.get(),
                                rhs[index2].r.get(),
                            )
                        ).Then(phase.inc(), Continue())
                    ),
                    index2.inc(),
                    If(index2 == rhs_size).Then(
                        index.inc(),
                        index2.store(0),
                    ),
                    If(index == rhs_size).Then(
                        phase.inc(),
                    ),
                )
                .Else(Break()),
                Nop(),
            ),
            self.flush(state, cached),
            self.set_solution(ans),
            Return(TRUE),
        )
