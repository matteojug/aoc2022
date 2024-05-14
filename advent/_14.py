from pyteal import *
from beaker import *
from beaker.decorators import *
from beaker.consts import TRUE

from .base import Base
from .utils import (
    BoxArray,
    BoxScratchStore,
    Forever,
    Max,
    Min,
    Nop,
    SScratchVar,
    BoxAllocator,
)

MAP_W = 150
MAP_H = 200


class Solution(Base):
    work_bytes = ReservedAccountStateValue(TealType.bytes, max_keys=1)

    def work_box_size(self):
        return 8 * 13 + MAP_W * MAP_H

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
            minX := SScratchVar(TealType.uint64),
            maxX := SScratchVar(TealType.uint64),
            maxY := SScratchVar(TealType.uint64),
            cnt := SScratchVar(TealType.uint64),
            shift := SScratchVar(TealType.uint64),
            X := SScratchVar(TealType.uint64),
            Y := SScratchVar(TealType.uint64),
            lastX := SScratchVar(TealType.uint64),
            lastY := SScratchVar(TealType.uint64),
            cnt2 := SScratchVar(TealType.uint64),
            h_left := SScratchVar(TealType.uint64),
            h_right := SScratchVar(TealType.uint64),
        )
        map = BoxArray(alloc, 1, MAP_H * MAP_W)
        cached = [scratch]

        INF = 2**64 - 1

        map_coord = lambda x, y: x + y * Int(MAP_W)
        map_get = lambda x, y: map[map_coord(x, y)].get()
        map_set = lambda x, y, v: map[map_coord(x, y)].set(v)

        return Seq(
            self.init_state(state),
            self.load_work(state),
            (tmp := SScratchVar()).store(0),
            If(work_box == "")
            .Then(
                work_box.store(self.work_box()),
                Seq([x.cache() for x in cached]),
                scratch.init(),
                minX.store(INF),
            )
            .Else(Seq([x.cache() for x in cached])),
            #
            Forever().Do(
                self.check_low_budget(self.flush(state, cached), 14),
                #
                If(phase == 0)
                .Then(
                    Assert(self.reader_next_uint(tmp)),
                    If(tmp < minX).Then(minX.store(tmp)),
                    If(tmp > maxX).Then(maxX.store(tmp)),
                    Assert(self.reader_next_uint(tmp)),
                    If(tmp > maxY).Then(maxY.store(tmp)),
                    If(self.reader_done()).Then(
                        Assert(maxY < MAP_H),
                        Assert(maxX - minX < Int(MAP_W)),
                        shift.store(minX - 1),
                        self.reader_seek(0),
                        phase.inc(),
                        lastX.store(INF),
                    ),
                    If(
                        self.reader_get(self.reader_index().load(), Int(1))
                        == Bytes("-")
                    ).Then(self.reader_index().inc(3)),
                )
                .ElseIf(phase == 1)
                .Then(
                    Assert(self.reader_next_uint(X)),
                    X.dec(shift),
                    Assert(self.reader_next_uint(Y)),
                    If(lastX != INF).Then(
                        If(X == lastX)
                        .Then(
                            (lim := SScratchVar()).store(Max(Y.load(), lastY.load())),
                            For(
                                (i := SScratchVar()).store(Min(Y.load(), lastY.load())),
                                i <= lim,
                                i.inc(),
                            ).Do(map_set(X, i, "#")),
                        )
                        .ElseIf(Y == lastY)
                        .Then(
                            (lim := SScratchVar()).store(Max(X.load(), lastX.load())),
                            For(
                                (i := SScratchVar()).store(Min(X.load(), lastX.load())),
                                i <= lim,
                                i.inc(),
                            ).Do(map_set(i, Y, "#")),
                        )
                    ),
                    If(self.reader_done())
                    .Then(
                        phase.inc(),
                    )
                    .ElseIf(
                        self.reader_get(self.reader_index().load(), Int(1))
                        == Bytes("-")
                    )
                    .Then(
                        self.reader_index().inc(3),
                        lastX.store(X),
                        lastY.store(Y),
                    )
                    .Else(
                        lastX.store(INF),
                    ),
                )
                .ElseIf(phase == 2)
                .Then(
                    X.store(500),
                    X.dec(shift),
                    Y.store(0),
                    Forever().Do(
                        tmp.store(Y + 1),
                        If(map_get(X, tmp) == Bytes("\0"))
                        .Then(
                            Y.inc(),
                        )
                        .ElseIf(map_get(X - 1, tmp) == Bytes("\0"))
                        .Then(
                            Y.inc(),
                            X.dec(),
                        )
                        .ElseIf(map_get(X + 1, tmp) == Bytes("\0"))
                        .Then(
                            Y.inc(),
                            X.inc(),
                        )
                        .Else(map_set(X, Y, "o"), cnt.inc(), Break()),
                        If(Y > maxY).Then(
                            phase.inc(),
                            cnt2.inc(),
                            X.store(500),
                            X.dec(shift),
                            Y.store(0),
                            map_set(X, Y, "X"),
                            Y.inc(),
                            Break(),
                        ),
                    ),
                )
                .ElseIf(phase == 3)
                .Then(
                    If(Int(500) - shift.load() >= Y.load())
                    .Then(X.store(Int(500) - shift.load() - Y.load()))
                    .Else(
                        X.store(0),
                    ),
                    (ok := SScratchVar()).store(0),
                    (y := SScratchVar()).store(Y - 1),
                    tmp.store(maxX + 1 - shift.load()),
                    For(
                        (lim := SScratchVar()).store(
                            Min(tmp.load(), Int(500) - shift.load() + Y.load())
                        ),
                        X <= lim,
                        X.inc(),
                    ).Do(
                        If(map_get(X, Y) == Bytes("#")).Then(Continue()),
                        ok.store(0),
                        If(X > 0).Then(
                            If(map_get(X - 1, y) == Bytes("X")).Then(ok.store(1))
                        ),
                        If(map_get(X, y) == Bytes("X")).Then(ok.store(1)),
                        If(map_get(X + 1, y) == Bytes("X")).Then(ok.store(1)),
                        If(ok.load()).Then(
                            map_set(X, Y, "X"),
                            cnt2.inc(),
                            If(And(X == 0, h_left == 0)).Then(h_left.store(Y)),
                            If(And(X == tmp.load(), h_right == 0)).Then(
                                h_right.store(Y)
                            ),
                        ),
                    ),
                    Y.inc(),
                    If(Y == maxY + 2).Then(
                        tmp.store(maxY + 2 - h_left.load()),
                        cnt2.inc(tmp * (tmp - 1) / Int(2)),
                        tmp.store(maxY + 2 - h_right.load()),
                        cnt2.inc(tmp * (tmp - 1) / Int(2)),
                        phase.inc(),
                    ),
                )
                .Else(Break()),
                Nop(),
            ),
            self.flush(state, cached),
            self.set_solution(cnt, cnt2),
            Return(TRUE),
        )
