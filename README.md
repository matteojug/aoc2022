# PyTeal @ Advent of Code 2022

Partial solutions for Advent of Code 2022 using PyTeal.

Since I wanted to use pyteal for everything, starting from the parsing of the puzzle, the setup is that all the input is first transferred to a SC Box, then the SC is invoked multiple times to do units of work until it signals that the solution is ready; at that point, we get the solution and clear the box to reclaim the funds.

The general flow is:
 - Compile, deploy and fund the smart contract (`ClientBase.create`)
 - Prepare the input box (`ClientBase.input`):
   - Opt-in to the SC, specifying the input size, and get the required funds for the box(es) and/or state var
   - Get the box refs to be used to populate the right boxes
   - Fund the SC to solve the specific problem instance
   - Send the input to the SC in chunks of ~2k bytes
 - Solve the input (`ClientBase.solve`):
   - Get the box refs to be used to read the right boxes
   - Call `solve` method until it signals the completion
   - Call `get_solution` to log the solution
 - Clear the input box and reclaim the funds (`ClientBase.clear`)

Most of those things are handled by some scaffolding; the solution is implemented in each `_{day}.py` module, within its `Solution.solve_impl` method.

Part of the code was golfed to reduce the opcode budget, so there are a lot of inlined operations, cached stuff or funny things.

Obvious disclaimer: do not trust this code to do anything remotely safe.

## Run the code

Install the pipenv, then `pipenv shell`. Then `docker compose up` to bring up the sandbox.

To run a specific day (using dockerized sandbox and example input), run:

```bash
python -m advent 1 --example
```

To run on non example instances, put the problem input in `inputs/{day}.txt`, then:

```bash
python -m advent 1
```

## Stats

Some stats:
 - `input-size`: byte size of the problem input
 - `teal-size`: byte size of the smart contract bytecode
 - `iters`: number of iterations, each one being an atomic group with max opcode budget
 - `opcode-budget`: total opcode budget used
 - `cost-final`: txn cost (algos) to solve the instance
 - `funds`: required total funds (algos) to solve the instance (to pay for boxes and co, returned on clear)

```bash
python -m advent -15 --quiet

  day    input-size    teal-size    iters    opcode-budget  cost-final    funds        solutions
-----  ------------  -----------  -------  ---------------  ------------  -----------  ---------------------------
    1         10476         1571        3           354959  0.889000Ⱥ     5.104500Ⱥ    [71780, 212489]
    2         10000         1413        2           210320  0.629001Ⱥ     4.654101Ⱥ    [11666, 12767]
    3          9968         2011        4           516710  1.146000Ⱥ     5.158300Ⱥ    [8105, 2363]
    4         11370         1445        2           345061  0.631000Ⱥ     5.204100Ⱥ    [471, 888]
    5          9949         2665        2           214130  0.630000Ⱥ     5.526800Ⱥ    ['GRTSWNJHH', 'QLFQDBBHM']
    6          4096         1883        2           269918  0.625000Ⱥ     2.400800Ⱥ    [1816, 2625]
    7         10576         2283        3           403718  0.889000Ⱥ     5.812600Ⱥ    [1844187, 4978279]
    8          9900         3447       33          5521939  8.627009Ⱥ     13.160209Ⱥ   [1776, 234416]
    9          8388         5475       32          5191132  8.435015Ⱥ     20.084615Ⱥ   [6087, 2493]
   10           967         2539        1            26601  0.366000Ⱥ     0.912600Ⱥ    ['15880', ...]
   11          1278         2773      743        126656806  191.042813Ⱥ   192.595413Ⱥ  [110888, 25590400731]
   12          4182         3203        6           905700  1.675000Ⱥ     12.224600Ⱥ   [361, 354]
   13         21989         2301        4           537323  1.156001Ⱥ     10.020601Ⱥ   [5938, 29025]
   14         25431         2918       38          6308247  10.120030Ⱥ    32.382230Ⱥ   [961, 26375]
   15          1904         3699        2           308082  0.623000Ⱥ     1.962000Ⱥ    [5112034, 13172087230812]

```

```bash
python -m advent -15 --quiet --example

  day    input-size    teal-size    iters    opcode-budget  cost-final    funds       solutions
-----  ------------  -----------  -------  ---------------  ------------  ----------  ---------------------------
    1            55         1571        1             2201  0.366000Ⱥ     0.414100Ⱥ   [24000, 45000]
    2            12         1413        1              331  0.366000Ⱥ     0.396900Ⱥ   [15, 12]
    3           150         2011        1             8916  0.366000Ⱥ     0.452100Ⱥ   [157, 70]
    4            48         1445        1             1527  0.365001Ⱥ     0.410301Ⱥ   [2, 4]
    5           125         2665        1             2829  0.366000Ⱥ     1.334200Ⱥ   ['CMZ', 'MCD']
    6            31         1883        1             1860  0.366000Ⱥ     0.515800Ⱥ   [7, 19]
    7           192         2283        1            10400  0.366000Ⱥ     1.137000Ⱥ   [95437, 24933642]
    8            30         3447        1             9298  0.366000Ⱥ     0.952200Ⱥ   [21, 8]
    9            36         5475        1            64880  0.371001Ⱥ     8.680801Ⱥ   [88, 36]
   10           980         2539        1            26634  0.366000Ⱥ     0.917800Ⱥ   ['13140', ...]
   11           610         2773      127         21617019  32.745051Ⱥ    34.030451Ⱥ  [10605, 2713310158]
   12            45         3203        1            11476  0.372000Ⱥ     9.267800Ⱥ   [31, 29]
   13           186         2301        1            14781  0.366000Ⱥ     0.511400Ⱥ   [13, 140]
   14            57         2918        1            20723  0.375000Ⱥ     12.490600Ⱥ  [24, 93]
   15           738         3699        1            59226  0.366000Ⱥ     1.238600Ⱥ   [26, 56000011]

```
