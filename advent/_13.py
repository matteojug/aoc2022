from pyteal import *
from beaker import *
from beaker.decorators import *
from beaker.consts import TRUE

from .base import Base
from .utils import BoxScratchStore, Forever, Nop, SScratchVar, BoxAllocator, atoish


class Solution(Base):
    work_bytes = ReservedAccountStateValue(TealType.bytes, max_keys=1)

    def work_box_size(self):
        return 8 * 4 + 10

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
            pair_index := SScratchVar(TealType.uint64),
            total := SScratchVar(TealType.uint64),
            lt_2 := SScratchVar(TealType.uint64),
            lt_6 := SScratchVar(TealType.uint64),
            (seq_2 := SScratchVar(TealType.bytes), 5),
            (seq_6 := SScratchVar(TealType.bytes), 5),
        )
        cached = [scratch]

        @Subroutine(TealType.uint64)
        def is_less(a_: Expr, b_: Expr):
            return Seq(
                (a := SScratchVar()).store(a_),
                (b := SScratchVar()).store(b_),
                (ai := SScratchVar()).store(0),
                (bi := SScratchVar()).store(0),
                (af := SScratchVar()).store(0),
                (bf := SScratchVar()).store(0),
                Forever().Do(
                    (ac := SScratchVar()).store(GetByte(a.load(), ai.load())),
                    (bc := SScratchVar()).store(GetByte(b.load(), bi.load())),
                    If(ac == ord(","))
                    .Then(If(bc == ord(",")).Then(ai.inc(), bi.inc()).Else(Break()))
                    .ElseIf(bc == ord(","))
                    .Then(Return(Int(1)))
                    .ElseIf(ac == ord("["))
                    .Then(
                        If(bc == ord("["))
                        .Then(ai.inc(), bi.inc())
                        .ElseIf(bc == ord("]"))
                        .Then(Break())
                        .Else(bf.inc(), ai.inc())
                    )
                    .ElseIf(bc == ord("["))
                    .Then(If(ac == ord("]")).Then(Return(Int(1))), af.inc(), bi.inc())
                    .ElseIf(ac == ord("]"))
                    .Then(
                        If(bc == ord("]")).Then(ai.inc(), bi.inc()).Else(Return(Int(1)))
                    )
                    .ElseIf(bc == ord("]"))
                    .Then(Break())
                    .Else(
                        (an := SScratchVar()).store(atoish(a.load(), ai)),
                        (bn := SScratchVar()).store(atoish(b.load(), bi)),
                        If(an < bn).Then(Return(Int(1))).ElseIf(an > bn).Then(Break()),
                        For((tmp := SScratchVar()).store(0), tmp < af, tmp.inc()).Do(
                            ai.dec(),
                            a.store(SetByte(a.load(), ai.load(), Int(ord("]")))),
                        ),
                        For((tmp := SScratchVar()).store(0), tmp < bf, tmp.inc()).Do(
                            bi.dec(),
                            b.store(SetByte(b.load(), bi.load(), Int(ord("]")))),
                        ),
                    ),
                    Nop(),
                ),
                Return(Int(0)),
            )

        return Seq(
            self.init_state(state),
            self.load_work(state),
            If(work_box == "")
            .Then(
                work_box.store(self.work_box()),
                Seq([x.cache() for x in cached]),
                scratch.init(),
                seq_2.store("[[2]]"),
                seq_6.store("[[6]]"),
            )
            .Else(Seq([x.cache() for x in cached])),
            #
            While(self.reader_available()).Do(
                self.check_low_budget(self.flush(state, cached), 10),
                pair_index.inc(),
                (a := SScratchVar()).store(self.reader_next_line_long()),
                (b := SScratchVar()).store(self.reader_next_line_long()),
                If(is_less(a.load(), b.load())).Then(total.inc(pair_index)),
                #
                If(is_less(a.load(), seq_2.load()))
                .Then(lt_2.inc(), lt_6.inc())
                .ElseIf(is_less(a.load(), seq_6.load()))
                .Then(lt_6.inc()),
                #
                If(is_less(b.load(), seq_2.load()))
                .Then(lt_2.inc(), lt_6.inc())
                .ElseIf(is_less(b.load(), seq_6.load()))
                .Then(lt_6.inc()),
                #
                If(self.reader_available()).Then(a.store(self.reader_next(Int(1)))),
                Nop(),
            ),
            self.flush(state, cached),
            self.set_solution(total, (lt_2 + 1) * (lt_6 + 2)),
            Return(TRUE),
        )
