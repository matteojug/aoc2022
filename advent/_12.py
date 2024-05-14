from pyteal import *
from pyteal.ast.abi.uint import uint_encode
from beaker import *
from beaker.decorators import *
from beaker.consts import TRUE, FALSE

from .base import Base
from .utils import (
    BoxArrayCustom,
    BoxScratchStore,
    Forever,
    SScratchVar,
    BoxAllocator,
)

MAX_ROWS = 50
MAX_COLS = 110
MAX_MAP = MAX_ROWS * MAX_COLS


class Solution(Base):
    work_bytes = ReservedAccountStateValue(TealType.bytes, max_keys=1)

    def work_box_size(self):
        return 8 * 8 + 2 * MAX_MAP * 2

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
            start := SScratchVar(TealType.uint64),
            end := SScratchVar(TealType.uint64),
            rows := SScratchVar(TealType.uint64),
            cols := SScratchVar(TealType.uint64),
            size := SScratchVar(TealType.uint64),
            queue_start := SScratchVar(TealType.uint64),
            queue_end := SScratchVar(TealType.uint64),
            best := SScratchVar(TealType.uint64),
        )
        dist = BoxArrayCustom(
            alloc,
            2,
            MAX_MAP,
            lambda x: uint_encode(16, x),
            lambda x: ExtractUint16(x, Int(0)),
        )
        queue = BoxArrayCustom(
            alloc,
            2,
            MAX_MAP,
            lambda x: uint_encode(16, x),
            lambda x: ExtractUint16(x, Int(0)),
        )
        cached = [scratch]

        map_index = lambda x: x + x / cols
        UNK = Int(2**16 - 1)

        qp = SScratchVar(TealType.uint64)
        push = lambda x: Seq(queue[queue_end].set(x), queue_end.inc())
        pop = lambda x=qp: Seq(x.store(queue[queue_start].get()), queue_start.inc())

        c = SScratchVar()
        nd = SScratchVar(TealType.uint64)

        def to_height(w):
            return Seq(
                (tmp := SScratchVar()).store(w),
                If(tmp == "S")
                .Then(Int(ord("a")))
                .ElseIf(tmp == "E")
                .Then(Int(ord("z")))
                .Else(GetByte(tmp.load(), Int(0))),
            )

        def check_neighbor(cond, next_):
            @Subroutine(TealType.uint64)
            def _fn(nh, nd):
                return Seq(
                    If(cond).Then(
                        (next := SScratchVar()).store(next_),
                        If(dist[next].get() != UNK).Then(Return(FALSE)),
                        (next_h := SScratchVar()).store(
                            to_height(self.reader_get(map_index(next), Int(1)))
                        ),
                        If(next_h.load() < nh).Then(Return(FALSE)),
                        #
                        dist[next].set(nd),
                        If(next_h == ord("a")).Then(
                            If(nd < best.load()).Then(best.store(nd)),
                        ),
                        If(next == start).Then(Return(TRUE)),
                        push(next),
                    ),
                    Return(FALSE),
                )

            return _fn(nh.load(), nd.load())

        return Seq(
            qp.store(0),
            self.init_state(state),
            self.load_work(state),
            If(work_box == "")
            .Then(
                work_box.store(self.work_box()),
                Seq([x.cache() for x in cached]),
                scratch.init(),
                cols.store(Len(self.reader_next_line())),
                rows.store(self.input_size.get() / (cols + 1)),
                size.store(cols * rows),
                #
                (line := SScratchVar()).store(""),
                For((i := SScratchVar()).store(0), i < MAX_ROWS, i.inc()).Do(
                    dist.area.replace(
                        i * (MAX_COLS * dist.element_size), b"\xff\xff" * MAX_COLS
                    ),
                ),
                For((i := SScratchVar()).store(0), i < size, i.inc()).Do(
                    (z := SScratchVar()).store(i % cols),
                    If(z.load())
                    .Then(Seq())
                    .Else(
                        line.store(self.reader_get(map_index(i), cols.load())),
                    ),
                    c.store(GetByte(line.load(), z.load())),
                    If(c == ord("S"))
                    .Then(start.store(i))
                    .ElseIf(c == ord("E"))
                    .Then(end.store(i)),
                ),
                push(end),
                dist[end].set(0),
                best.store(UNK),
            )
            .Else(Seq([x.cache() for x in cached])),
            #
            Forever().Do(
                self.check_low_budget(self.flush(state, cached)),
                pop(),
                c.store(self.reader_get(map_index(qp), Int(1))),
                (nh := SScratchVar(TealType.uint64)).store(
                    to_height(c.load()) - Int(1)
                ),
                nd.store(dist[qp].get() + Int(1)),
                If(
                    Or(
                        check_neighbor(qp >= cols, qp - cols),
                        check_neighbor(qp < size - cols, qp + cols),
                        check_neighbor(qp % cols, qp - 1),
                        check_neighbor((qp + 1) % cols.load(), qp + 1),
                    )
                ).Then(Break()),
            ),
            self.flush(state, cached),
            self.set_solution(dist[start], best),
            Return(TRUE),
        )
