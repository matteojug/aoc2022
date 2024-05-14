from pyteal import *
from beaker import *
from beaker.decorators import *
from beaker.consts import TRUE

from .base import Base
from .utils import SScratchVar, BoxAllocator, BoxArray, BoxArrayUint, Forever


MAX_COLS = 10
MAX_START_HEIGHT = 10


class Solution(Base):
    work_ints = ReservedAccountStateValue(TealType.uint64, max_keys=1)
    work_bytes = ReservedAccountStateValue(TealType.bytes, max_keys=1)

    part_one: AccountStateValue = AccountStateValue(TealType.bytes)
    part_two: AccountStateValue = AccountStateValue(TealType.bytes)

    @external
    def get_solution(self, *, output: abi.Tuple2[abi.String, abi.String]):
        return Seq(
            (part_one := abi.String()).set(self.part_one.get()),
            (part_two := abi.String()).set(self.part_two.get()),
            output.set(part_one, part_two),
        )

    def work_box_size(self):
        return 2 * MAX_COLS * (8 + MAX_START_HEIGHT * MAX_COLS)

    def flush(self, state: dict, cached):
        return Seq(self.save_work(state), Seq([x.flush() for x in cached]))

    def load_initial(
        self, cols: SScratchVar, col_len: BoxArrayUint, col_boxes: BoxArray
    ):
        return Seq(
            For((i := SScratchVar()).store(0), i < MAX_COLS, i.inc()).Do(
                col_len[i].set(0),
                col_boxes[i].set(b"\0" * (MAX_START_HEIGHT * MAX_COLS)),
            ),
            Forever().Do(
                (line := SScratchVar(TealType.bytes)).store(self.reader_next_line()),
                If(Extract(line.load(), Int(1), Int(1)) == Bytes("1")).Then(Break()),
                (line_len := SScratchVar()).store(Len(line.load())),
                For(i.store(0), Int(1) + i * 4 < line_len.load(), i.inc()).Do(
                    (c := SScratchVar()).store(
                        Extract(line.load(), Int(1) + i * 4, Int(1))
                    ),
                    If(c == " ").Then(Continue()),
                    (j := SScratchVar()).store(col_len[i].get()),
                    col_boxes[i].set(Replace(col_boxes[i].get(), j.load(), c.load())),
                    col_len[i].set(j + 1),
                ),
            ),
            cols.store((Len(line.load()) + Int(1)) / Int(4)),
            Pop(self.reader_next_line()),
        )

    @internal(TealType.uint64)
    def solve_impl(self):
        state = dict(work_box=(work_box := SScratchVar()), cols=(cols := SScratchVar()))
        alloc = BoxAllocator(work_box.load())
        col_len = BoxArrayUint(alloc, MAX_COLS)
        col_boxes = BoxArray(alloc, MAX_START_HEIGHT * MAX_COLS, MAX_COLS)
        col_len_2 = BoxArrayUint(alloc, MAX_COLS)
        col_boxes_2 = BoxArray(alloc, MAX_START_HEIGHT * MAX_COLS, MAX_COLS)
        cached = [col_len, col_boxes, col_len_2, col_boxes_2]

        return Seq(
            work_box.store(""),
            cols.store(0),
            self.load_work(state),
            If(work_box == "")
            .Then(
                work_box.store(self.work_box()),
                Seq([x.cache() for x in cached]),
                self.load_initial(cols, col_len, col_boxes),
                col_len_2.area.copy(col_len.area),
                col_boxes_2.area.copy(col_boxes.area),
            )
            .Else(Seq([x.cache() for x in cached])),
            (cnt := SScratchVar()).store(0),
            (idx_from := SScratchVar()).store(0),
            (idx_to := SScratchVar()).store(0),
            While(self.reader_available()).Do(
                self.check_low_budget(self.flush(state, cached), 3),
                self.reader_index().inc(5),
                Assert(self.reader_next_uint(cnt)),
                self.reader_index().inc(5),
                Assert(self.reader_next_uint(idx_from)),
                self.reader_index().inc(3),
                Assert(self.reader_next_uint(idx_to)),
                #
                idx_from.dec(),
                idx_to.dec(),
                #
                (col_from := SScratchVar()).store(col_boxes[idx_from].get()),
                (col_to := SScratchVar()).store(col_boxes[idx_to].get()),
                For((i := SScratchVar()).store(0), i < cnt, i.inc()).Do(
                    col_to.store(
                        Concat(
                            Extract(col_from.load(), i.load(), Int(1)), col_to.load()
                        )
                    ),
                ),
                col_boxes[idx_to].set(
                    Extract(col_to.load(), Int(0), Int(col_boxes.element_size))
                ),
                col_boxes[idx_from].set(Suffix(col_from.load(), cnt.load())),
                col_len[idx_from].set(col_len[idx_from].get() - cnt.load()),
                col_len[idx_to].set(col_len[idx_to].get() + cnt.load()),
                #
                col_from.store(col_boxes_2[idx_from].get()),
                col_boxes_2[idx_to].set(
                    Extract(
                        Concat(
                            Extract(col_from.load(), Int(0), cnt.load()),
                            col_boxes_2[idx_to].get(),
                        ),
                        Int(0),
                        Int(col_boxes.element_size),
                    )
                ),
                col_boxes_2[idx_from].set(Suffix(col_from.load(), cnt.load())),
                col_len_2[idx_from].set(col_len_2[idx_from].get() - cnt.load()),
                col_len_2[idx_to].set(col_len_2[idx_to].get() + cnt.load()),
            ),
            self.flush(state, cached),
            (sol1 := SScratchVar(TealType.bytes)).store(""),
            (sol2 := SScratchVar(TealType.bytes)).store(""),
            For((i := SScratchVar()).store(0), i < cols, i.inc()).Do(
                sol1.concat(Extract(col_boxes[i].get(), Int(0), Int(1))),
                sol2.concat(Extract(col_boxes_2[i].get(), Int(0), Int(1))),
            ),
            self.set_solution(sol1.load(), sol2.load()),
            Return(TRUE),
        )
