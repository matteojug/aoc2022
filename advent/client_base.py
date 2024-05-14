from tqdm import tqdm
import base64

from beaker import *

from algosdk.atomic_transaction_composer import (
    AtomicTransactionComposer,
    AccountTransactionSigner,
    TransactionWithSigner,
)
from algosdk import transaction
from algosdk.constants import MIN_TXN_FEE, TX_GROUP_LIMIT

from .third_party.account import Account, AppAccount
from .base import Base
from .utils import fmt_algo


MAX_ARG_SIZE = 2048 - 4 - 2  # Method selector and abi encoding


def chunk(data):
    return [data[i : i + MAX_ARG_SIZE] for i in range(0, len(data), MAX_ARG_SIZE)]


def dummy_gen():
    i = 0
    while True:
        yield i
        i += 1


class ClientBase:
    @staticmethod
    def instantiate(cls, test):
        return cls(test)

    @staticmethod
    def create(sol: Base, user: Account, verbose=True):
        app_client = client.ApplicationClient(
            client=user.algod_client,
            app=sol,
            signer=AccountTransactionSigner(user.private_key),
        )

        app_id, app_addr, _ = app_client.create()
        if verbose:
            print(f"App ID: {app_id} | Address: {app_addr}")
        app = AppAccount.from_app_id(app_id, algod_client=app_client.client)

        assert (mb := app.algod_client.account_info(app.address)["min-balance"]) < 1e6
        user.pay(app, mb)

        return (
            app,
            app_client.app.compile()[0],
            {
                "teal-size": len(app_client.approval_binary)
                + len(app_client.clear_binary)
            },
        )

    @staticmethod
    def input(sol: Base, user: Account, app: AppAccount, input: str, verbose=True):
        assert input.endswith("\n"), "Missing newline at the end, careful"

        app_client = client.ApplicationClient(
            client=user.algod_client,
            app=sol,
            signer=AccountTransactionSigner(user.private_key),
            app_id=app.app_id,
        )

        chunks = chunk(input)
        ret = {"input-size": len(input), "chunks": len(chunks)}
        if verbose:
            print(f"Input size: {len(input)}, {len(chunks)} chunks")

        input_funds = app_client.call(
            sol.opt_in,
            sender_addr=user.address,
            input_size=len(input),
            on_complete=transaction.OnComplete.OptInOC,
        ).return_value
        input_boxes, box_budget = app_client.call(sol.get_boxes).return_value
        # print(f"Input box: {input_box}")
        ret["box-funds"] = input_funds
        ret["box-budget"] = box_budget
        app_client.call(
            sol.deposit,
            txn=TransactionWithSigner(
                transaction.PaymentTxn(
                    user.address,
                    user._get_params(),
                    app.address,
                    input_funds,
                ),
                user,
            ),
        )
        atc = None
        res = []
        relevant_txn = None
        for i, c in enumerate(chunks):
            if atc is None:
                atc = AtomicTransactionComposer()

            app_client.add_method_call(
                atc,
                sol.input_append,
                chunk=c,
                boxes=boxes_fmt(input_boxes),
            )
            if len(atc.txn_list) == TX_GROUP_LIMIT or i == len(chunks) - 1:
                relevant_txn = len(atc.txn_list) - 1
                ensure_box_budget(atc, app_client, sol.nop, box_budget)
                res.extend(atc.execute(app_client.client, 0).abi_results)
                atc = None
        assert res[relevant_txn].return_value == len(input), "Stored input mismatch"

        # print(user.app_local_state(app))
        ret.update(
            app_min_balance=(
                min_balance := app.algod_client.account_info(app.address)["min-balance"]
            )
        )
        if verbose:
            print("App min balance:", fmt_algo(min_balance))
        return ret

    @staticmethod
    def solve(
        sol: Base, user: Account, app: AppAccount, verbose=True, debug=False, log=False
    ):
        app_client = client.ApplicationClient(
            client=user.algod_client,
            app=sol,
            signer=AccountTransactionSigner(user.private_key),
            app_id=app.app_id,
        )
        input_boxes, box_budget = app_client.call(sol.get_boxes).return_value

        total_budget = 0
        for iters in tqdm(dummy_gen()):
            atc = AtomicTransactionComposer()
            app_client.add_method_call(
                atc,
                sol.solve,
                boxes=boxes_fmt(input_boxes),
                suggested_params=user._get_params(fee=MIN_TXN_FEE * 257),
            )
            ensure_box_budget(atc, app_client, sol.nop, box_budget)
            atc_res = atc.execute(app_client.client, 0)

            # Debug helper
            if log:
                print(atc_res.abi_results[0].tx_info["logs"])
                for log in atc_res.abi_results[0].tx_info["logs"][:-1]:
                    print(base64.b64decode(log.encode()))

            res = atc_res.abi_results[0].return_value
            total_budget += res[1]
            if res[0]:
                break

        solutions = app_client.call(sol.get_solution).return_value
        if verbose:
            print("Total budget consumed:", total_budget)
            print("Solution:", solutions)
        return {
            "opcode-budget": total_budget,
            "iters": iters + 1,
            "solutions": solutions,
        }

    @staticmethod
    def clear(sol: Base, user: Account, app: AppAccount, verbose=True):
        app_client = client.ApplicationClient(
            client=user.algod_client,
            app=sol,
            signer=AccountTransactionSigner(user.private_key),
            app_id=app.app_id,
        )
        input_boxes, box_budget = app_client.call(sol.get_boxes).return_value

        atc = AtomicTransactionComposer()
        app_client.add_method_call(
            atc,
            sol.input_clear,
            boxes=boxes_fmt(input_boxes),
            suggested_params=user._get_params(fee=MIN_TXN_FEE * 2),
        )
        ensure_box_budget(atc, app_client, sol.nop, box_budget)
        res = atc.execute(app_client.client, 0).abi_results[0].return_value

        if verbose:
            print("Input close reclaimed:", fmt_algo(res))
        return {"reclaimed": res}


def ensure_box_budget(atc, app_client, fn, budget):
    budget -= sum(len(txn.txn.boxes) * 1024 for txn in atc.txn_list)
    for i in range(len(atc.txn_list), TX_GROUP_LIMIT - 1):
        if budget <= 0:
            break
        app_client.add_method_call(atc, fn, boxes=[[0, ""]] * 8, note=str(i))
        budget -= 1024 * 8


def boxes_fmt(input_boxes):
    return [[0, i] for i in input_boxes] + [[0, ""]] * (8 - len(input_boxes))
