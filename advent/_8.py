from pyteal import *
from beaker import *
from beaker.decorators import *
from beaker.consts import TRUE

from .base import Base
from .utils import (
    Min,
    Nop,
    SScratchVar,
    BoxAllocator,
    BoxArray,
    Forever,
)

MAX_SIDE = 100
MAX_LINES_BUFFERED = 4096 // (MAX_SIDE + 1)


class Solution(Base):
    work_ints = ReservedAccountStateValue(TealType.uint64, max_keys=6)
    work_bytes = ReservedAccountStateValue(TealType.bytes, max_keys=1)

    def work_box_size(self):
        return MAX_SIDE * (MAX_SIDE // 8 + 1)

    def flush(self, state: dict, cached):
        return Seq(self.save_work(state), Seq([x.flush() for x in cached]))

    @internal(TealType.uint64)
    def solve_impl(self):
        state = dict(
            work_box=(work_box := SScratchVar(TealType.bytes)),
            width=(width := SScratchVar(TealType.uint64)),
            height=(height := SScratchVar(TealType.uint64)),
            total=(total := SScratchVar(TealType.uint64)),
            index=(index := SScratchVar(TealType.uint64)),
            phase=(phase := SScratchVar(TealType.uint64)),
            best=(best := SScratchVar(TealType.uint64)),
        )
        alloc = BoxAllocator(work_box.load())
        mask = BoxArray(alloc, MAX_SIDE // 8 + 1, MAX_SIDE)
        cached = [mask]

        mask.cache()  # mark to be cached

        i = SScratchVar(TealType.uint64)
        w = SScratchVar(TealType.uint64)
        h = SScratchVar(TealType.uint64)
        cut = SScratchVar(TealType.uint64)
        c = SScratchVar(TealType.uint64)

        line_buffer = SScratchVar()

        Fetch = lambda x: c.store(
            GetByte(line_buffer.load(), x)
            if x
            else GetByte(self.reader_get(h * (width + 1) + w.load(), Int(1)), Int(0))
        )
        Check = lambda x, y=Seq(): Seq(
            Fetch(x),
            If(c <= cut).Then(y, Continue()),
            cut.store(c),
            If(GetBit(mask[h].get(), w.load())).Then(y, Continue()),
            mask[h].set(SetBit(mask[h].get(), w.load(), Int(1))),
            total.inc(),
            If(cut == ord("9")).Then(Break()),
        )
        Reset = lambda x: Seq(
            index.inc(),
            If(index == x).Then(
                phase.inc(),
                index.store(0),
            ),
        )

        @Subroutine(TealType.none)
        def LoopLeft():
            return Seq(
                h.store(index),
                line_buffer.store(self.reader_get(h * (width + 1), width.load())),
                For(w.store(0), w < width, w.inc()).Do(
                    Check(w.load()),
                ),
                Reset(height),
            )

        @Subroutine(TealType.none)
        def LoopRight():
            return Seq(
                h.store(index),
                line_buffer.store(self.reader_get(h * (width + 1), width.load())),
                w.store(width - 1),
                Forever().Do(
                    Check(
                        w.load(), (loop_step := Seq(If(w == 0).Then(Break()), w.dec()))
                    ),
                    loop_step,
                ),
                Reset(height),
            )

        @Subroutine(TealType.none)
        def LoopTop():
            return Seq(
                w.store(index),
                line_buffer.store(""),
                For(h.store(0), h < height, h.inc()).Do(
                    If(h % MAX_LINES_BUFFERED == Int(0)).Then(
                        i.store(h * (width + 1)),
                        line_buffer.store(
                            self.reader_get(
                                i.load(),
                                Min(
                                    (width + 1) * Int(MAX_LINES_BUFFERED),
                                    self.input_size.get() - i.load(),
                                ),
                            )
                        ),
                    ),
                    Check((h % MAX_LINES_BUFFERED) * (width + 1) + w.load()),
                ),
                Reset(width),
            )

        @Subroutine(TealType.none)
        def LoopBottom():
            return Seq(
                w.store(index),
                h.store(height - 1),
                (block_index_last := SScratchVar()).store(
                    h / MAX_LINES_BUFFERED * Int(MAX_LINES_BUFFERED)
                ),
                i.store(block_index_last * (width + 1)),
                line_buffer.store(
                    self.reader_get(
                        i.load(),
                        Min(
                            (width + 1) * Int(MAX_LINES_BUFFERED),
                            self.input_size.get() - i.load(),
                        ),
                    )
                ),
                Forever().Do(
                    (block_index := SScratchVar()).store(
                        h / MAX_LINES_BUFFERED * Int(MAX_LINES_BUFFERED)
                    ),
                    If(block_index != block_index_last).Then(
                        block_index_last.store(block_index),
                        i.store(block_index_last * (width + 1)),
                        line_buffer.store(
                            self.reader_get(
                                i.load(),
                                Min(
                                    (width + 1) * Int(MAX_LINES_BUFFERED),
                                    self.input_size.get() - i.load(),
                                ),
                            )
                        ),
                    ),
                    Check(
                        (h % MAX_LINES_BUFFERED) * (width + 1) + w.load(),
                        (loop_step := Seq(If(h == 0).Then(Break()), h.dec())),
                    ),
                    loop_step,
                ),
                Reset(width),
            )

        @Subroutine(TealType.none)
        def LookAround():
            return Seq(
                w.store(index % width),
                h.store(index / width),
                If(Or(w == 0, h == 0, w == width - 1, h == height - 1)).Then(
                    Reset(width * height), Return()
                ),
                line_buffer.store(self.reader_get(h * (width + 1), width.load())),
                Fetch(w.load()),
                cut.store(c),
                (w_orig := SScratchVar()).store(w),
                (h_orig := SScratchVar()).store(h),
                (score := SScratchVar()).store(1),
                #
                For(w.store(w_orig + 1), w < width, w.inc()).Do(
                    Fetch(w.load()), If(c >= cut).Then(Break())
                ),
                score.store(score * (Min(w.load(), width - 1) - w_orig.load())),
                #
                w.store(w_orig - 1),
                Forever().Do(
                    Fetch(w.load()),
                    If(c >= cut).Then(Break()),
                    If(w == 0).Then(Break()),
                    w.dec(),
                ),
                score.store(score * (w_orig - w.load())),
                #
                w.store(w_orig),
                h.store(h_orig + 1),
                i.store(
                    (h / MAX_LINES_BUFFERED * Int(MAX_LINES_BUFFERED)) * (width + 1)
                ),
                line_buffer.store(
                    self.reader_get(
                        i.load(),
                        Min(
                            (width + 1) * Int(MAX_LINES_BUFFERED),
                            self.input_size.get() - i.load(),
                        ),
                    )
                ),
                For(Seq(), h < height, h.inc()).Do(
                    If(h % MAX_LINES_BUFFERED == Int(0)).Then(
                        i.store(h * (width + 1)),
                        line_buffer.store(
                            self.reader_get(
                                i.load(),
                                Min(
                                    (width + 1) * Int(MAX_LINES_BUFFERED),
                                    self.input_size.get() - i.load(),
                                ),
                            )
                        ),
                    ),
                    Fetch((h % MAX_LINES_BUFFERED) * (width + 1) + w.load()),
                    If(c >= cut).Then(Break()),
                ),
                score.store(score * (Min(h.load(), height - 1) - h_orig.load())),
                #
                h.store(h_orig - 1),
                (block_index_last := SScratchVar()).store(
                    h / MAX_LINES_BUFFERED * Int(MAX_LINES_BUFFERED)
                ),
                i.store(block_index_last * (width + 1)),
                line_buffer.store(
                    self.reader_get(
                        i.load(),
                        Min(
                            (width + 1) * Int(MAX_LINES_BUFFERED),
                            self.input_size.get() - i.load(),
                        ),
                    )
                ),
                Forever().Do(
                    (block_index := SScratchVar()).store(
                        h / MAX_LINES_BUFFERED * Int(MAX_LINES_BUFFERED)
                    ),
                    If(block_index != block_index_last).Then(
                        block_index_last.store(block_index),
                        i.store(block_index_last * (width + 1)),
                        line_buffer.store(
                            self.reader_get(
                                i.load(),
                                Min(
                                    (width + 1) * Int(MAX_LINES_BUFFERED),
                                    self.input_size.get() - i.load(),
                                ),
                            )
                        ),
                    ),
                    Fetch((h % MAX_LINES_BUFFERED) * (width + 1) + w.load()),
                    If(c >= cut).Then(Break()),
                    If(h == 0).Then(Break()),
                    h.dec(),
                ),
                score.store(score * (h_orig - h.load())),
                #
                If(score > best).Then(best.store(score)),
                Reset(width * height),
            )

        return Seq(
            self.init_state(state),
            self.load_work(state),
            If(work_box == "")
            .Then(
                work_box.store(self.work_box()),
                Seq([x.cache() for x in cached]),
                (tmp := SScratchVar(TealType.bytes)).store(self.reader_next_line()),
                width.store(Len(tmp.load())),
                height.store(self.input_size.get() / (width + 1)),
                For(i.store(0), i < height, i.inc()).Do(
                    mask[i].set(b"\0" * mask.element_size)
                ),
            )
            .Else(Seq([x.cache() for x in cached])),
            Forever().Do(
                self.check_low_budget(self.flush(state, cached), 10),
                cut.store(ord("0") - 1),
                If(phase == 0)
                .Then(LoopLeft())
                .ElseIf(phase == 1)
                .Then(LoopTop())
                .ElseIf(phase == 2)
                .Then(LoopRight())
                .ElseIf(phase == 3)
                .Then(LoopBottom())
                .ElseIf(phase == 4)
                .Then(LookAround())
                .Else(Break()),
                Nop(),
            ),
            self.flush(state, cached),
            self.set_solution(total, best),
            Return(TRUE),
        )
