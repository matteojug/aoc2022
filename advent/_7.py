from pyteal import *
from beaker import *
from beaker.decorators import *
from beaker.consts import TRUE

from .base import Base
from .utils import Nop, SScratchVar, BoxAllocator, BoxArrayUint, Forever, Findi, atoi

MAX_DEPTH = 200  # >count(cd ..)
DISK_SIZE = 70000000
DISK_REQUIRED = 30000000


class Solution(Base):
    work_ints = ReservedAccountStateValue(TealType.uint64, max_keys=5)
    work_bytes = ReservedAccountStateValue(TealType.bytes, max_keys=1)

    def work_box_size(self):
        return MAX_DEPTH * 8

    def flush(self, state: dict, cached):
        return Seq(self.save_work(state), Seq([x.flush() for x in cached]))

    @internal(TealType.uint64)
    def solve_impl(self):
        state = dict(
            work_box=(work_box := SScratchVar(TealType.bytes)),
            phase=(phase := SScratchVar(TealType.uint64)),
            current=(current := SScratchVar(TealType.uint64)),
            total=(total := SScratchVar(TealType.uint64)),
            index=(index := SScratchVar(TealType.uint64)),
            target=(target := SScratchVar(TealType.uint64)),
        )
        alloc = BoxAllocator(work_box.load())
        path = BoxArrayUint(alloc, MAX_DEPTH)
        cached = [path]

        line = SScratchVar()

        return Seq(
            self.init_state(state),
            self.load_work(state),
            If(work_box == "")
            .Then(
                work_box.store(self.work_box()),
                Seq([x.cache() for x in cached]),
                path[0].set(0),
            )
            .Else(Seq([x.cache() for x in cached])),
            Forever().Do(
                self.check_low_budget(self.flush(state, cached), 2),
                If(self.reader_available())
                .Then(
                    line.store(self.reader_next_line()),
                )
                .Else(
                    If(index == 0).Then(
                        If(phase.load())
                        .Then(Break())
                        .Else(
                            self.set_solution(total),
                            self.reader_seek(0),
                            target.store(
                                Int(DISK_REQUIRED) - (Int(DISK_SIZE) - current.load())
                            ),
                            total.store(DISK_SIZE),
                            phase.inc(),
                            current.store(0),
                            Continue(),
                        ),
                    ),
                    line.store("$ cd .."),
                ),
                If(line == "$ ls")
                .Then(Nop(), Continue())
                .ElseIf(line == "$ cd ..")
                .Then(
                    If(phase.load())
                    .Then(
                        If(And(current >= target, current < total)).Then(
                            total.store(current)
                        )
                    )
                    .Else(
                        If(current < 100000).Then(total.inc(current)),
                    ),
                    index.dec(),
                    current.inc(path[index]),
                    Continue(),
                ),
                (line_pre := SScratchVar()).store(Extract(line.load(), Int(0), Int(4))),
                If(line_pre == Bytes("$ cd"))
                .Then(
                    path[index].set(current),
                    index.inc(),
                    current.store(0),
                )
                .ElseIf(line_pre == Bytes("dir "))
                .Then(Nop(), Continue())
                .Else(
                    (space := SScratchVar()).store(Findi(line, Int(ord(" ")))),
                    current.inc(atoi(Extract(line.load(), Int(0), space.load()))),
                ),
                Nop(),
            ),
            self.flush(state, cached),
            self.set_solution(part_two=total),
            Return(TRUE),
        )
