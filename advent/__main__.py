import argparse
import importlib
from pathlib import Path
from tabulate import tabulate
from beaker.sandbox import get_algod_client, get_accounts

from algosdk.v2client import algod
from algosdk.constants import MICROALGOS_TO_ALGOS_RATIO

from .third_party.account import Account, AppAccount
from .base import Base
from .client_base import ClientBase
from .utils import fmt_algo, solver_user

parser = argparse.ArgumentParser()
parser.add_argument("day", type=int)
parser.add_argument("--commit", action="store_true", default=False)
parser.add_argument("--teal", action="store_true", default=False)
parser.add_argument("--quiet", action="store_true", default=False)
parser.add_argument("--debug", action="store_true", default=False)
parser.add_argument("--log", action="store_true", default=False)
parser.add_argument("--example", action="store_true", default=False)
parser.add_argument("--app", type=int, default=None)

args = parser.parse_args()

if args.commit:
    alogd_client = algod.AlgodClient("", "https://testnet-api.algonode.cloud")
else:
    alogd_client = get_algod_client()

if args.day > 0:
    args.day = [args.day]
else:
    args.day = list(range(1, -args.day + 1))

day_stats = []
for day in args.day:
    input_file = (
        Path(__file__).parent
        / ".."
        / ("examples" if args.example else "inputs")
        / f"{day}.txt"
    )
    sol_module = importlib.import_module(f"._{day}", __package__)
    Solution = sol_module.Solution  # type: Base
    Client = getattr(sol_module, "Client", ClientBase)  # type: ClientBase

    user = solver_user(alogd_client)

    if not args.commit:
        faucet = get_accounts().pop()
        Account(faucet.address, faucet.private_key, algod_client=alogd_client).pay(
            user, 1000 * MICROALGOS_TO_ALGOS_RATIO
        )

    if not args.quiet:
        print("Solver user:", user.address)
        print("\tBalance:", fmt_algo(user.asa_balance(0)))
    init_balance = user.asa_balance(0)
    lowest_balance = user.asa_balance(0)

    solution = Client.instantiate(Solution, test=args.example)

    stats = {"day": day}

    if args.app:
        app = AppAccount.from_app_id(args.app, algod_client=user.algod_client)
        if user.app_local_state(app):
            user.app_clear_state(app)
        stats["teal-size"] = "?"
    else:
        balance = user.asa_balance(0)
        app, teal, stats_ = Client.create(solution, user, verbose=not args.quiet)

        if args.teal:
            with open(f"{day}.teal", "w") as f:
                f.write(teal)

        stats.update(stats_)
        stats["cost_setup"] = (delta := balance - user.asa_balance(0))
        if not args.quiet:
            print("Setup app cost:", fmt_algo(delta))
        lowest_balance = min(lowest_balance, user.asa_balance(0))

    balance = user.asa_balance(0)
    stats.update(
        **Client.input(
            solution, user, app, open(input_file).read(), verbose=not args.quiet
        )
    )
    stats["cost-input"] = (delta := balance - user.asa_balance(0))
    if not args.quiet:
        print("Input cost (incl box funding):", fmt_algo(delta))
    lowest_balance = min(lowest_balance, user.asa_balance(0))

    balance = user.asa_balance(0)
    stats.update(
        **Client.solve(
            solution,
            user,
            app,
            verbose=not args.quiet,
            debug=args.debug,
            log=args.log or args.debug,
        )
    )
    stats["cost-solve"] = (delta := balance - user.asa_balance(0))
    if not args.quiet:
        print("Solve cost:", fmt_algo(delta))
    lowest_balance = min(lowest_balance, user.asa_balance(0))

    stats.update(**Client.clear(solution, user, app, verbose=not args.quiet))
    lowest_balance = min(lowest_balance, user.asa_balance(0))

    stats["cost-final"] = (delta := init_balance - user.asa_balance(0))
    stats["funds"] = init_balance - lowest_balance
    if not args.quiet:
        # print(stats)
        print("Required algos to solve:", fmt_algo(init_balance - lowest_balance))
        print("Final cost:", fmt_algo(delta))

    day_stats.append(stats)

for k in ["box-funds", "cost-final", "funds"]:
    for r in day_stats:
        r[k] = fmt_algo(r[k])

headers = [
    "day",
    "input-size",
    "teal-size",
    "iters",
    "opcode-budget",
    "cost-final",
    "funds",
    "solutions",
]
day_stats = [[row[h] for h in headers] for row in day_stats]
print(tabulate(day_stats, headers=headers))
