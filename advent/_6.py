from pyteal import *
from beaker import *
from beaker.decorators import *
from beaker.consts import TRUE

from .base import Base
from .utils import Nop, SScratchVar, BoxAllocator, BoxArrayUint


DAT_ALPHABET = 26


class Solution(Base):
    work_ints = ReservedAccountStateValue(TealType.uint64, max_keys=3)
    work_bytes = ReservedAccountStateValue(TealType.bytes, max_keys=1)

    def work_box_size(self):
        return DAT_ALPHABET * 8

    def flush(self, state: dict, cached):
        return Seq(self.save_work(state), Seq([x.flush() for x in cached]))

    @internal(TealType.uint64)
    def solve_impl(self):
        state = dict(
            work_box=(work_box := SScratchVar(TealType.bytes)),
            unique=(unique := SScratchVar(TealType.uint64)),
            target_len=(target_len := SScratchVar(TealType.uint64)),
            sol1=(sol1 := SScratchVar(TealType.uint64)),
        )
        alloc = BoxAllocator(work_box.load())
        counters = BoxArrayUint(alloc, DAT_ALPHABET)
        cached = [counters]

        curr = SScratchVar()
        curr_index = SScratchVar()

        def fetch(how):
            return Seq(
                (c := SScratchVar()).store(how),
                curr_index.store(GetByte(c.load(), Int(0)) - Int(ord("a"))),
                curr.store(counters[curr_index].get()),
            )

        return Seq(
            self.init_state(state, target_len=4),
            self.load_work(state),
            If(work_box == "")
            .Then(
                work_box.store(self.work_box()),
                Seq([x.cache() for x in cached]),
                For((i := SScratchVar()).store(0), i < DAT_ALPHABET, i.inc()).Do(
                    counters[i].set(0),
                ),
                For((i := SScratchVar()).store(1), i < target_len, i.inc()).Do(
                    fetch(self.reader_next(Int(1))),
                    If(Not(curr.load())).Then(unique.inc()),
                    counters[curr_index].set(curr + 1),
                ),
            )
            .Else(Seq([x.cache() for x in cached])),
            While(self.reader_available()).Do(
                self.check_low_budget(self.flush(state, cached)),
                fetch(self.reader_next(Int(1))),
                If(Not(curr.load())).Then(unique.inc()),
                counters[curr_index].set(curr + 1),
                #
                If(unique == target_len).Then(
                    If(sol1 == 0)
                    .Then(
                        sol1.store(self.reader_index()),
                        For((i := SScratchVar()).store(target_len), i < 13, i.inc()).Do(
                            fetch(self.reader_next(Int(1))),
                            If(Not(curr.load())).Then(unique.inc()),
                            counters[curr_index].set(curr + 1),
                        ),
                        target_len.store(14),
                        Continue(),
                    )
                    .Else(Break())
                ),
                #
                If(self.reader_index() >= target_len).Then(
                    fetch(self.reader_get(self.reader_index() - target_len, Int(1))),
                    If(curr == 1).Then(unique.dec()),
                    counters[curr_index].set(curr - 1),
                ),
                Nop(),  # pyteal shenanigans
            ),
            self.flush(state, cached),
            self.set_solution(sol1, self.reader_index()),
            Return(TRUE),
        )
