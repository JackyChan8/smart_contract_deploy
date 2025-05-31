import os
import json
import sys
from dotenv import load_dotenv
from web3 import Web3
from web3.exceptions import ContractLogicError, TimeExhausted
from requests.exceptions import ReadTimeout

# ------------------------------------------------------------------------------
# 1. Загрузка окружения
# ------------------------------------------------------------------------------
load_dotenv()

IS_TEST = os.getenv('IS_TEST', 'false').lower() in ('1','true','yes')
if IS_TEST:
    RPC_URL_PRIMARY  = os.getenv('RPC_URL_TEST')
    RPC_URL_FALLBACK = os.getenv('RPC_URL_TEST_FALLBACK','')
    PRIVATE_KEY      = os.getenv('PRIVATE_KEY_TEST')
else:
    RPC_URL_PRIMARY  = os.getenv('RPC_URL')
    RPC_URL_FALLBACK = os.getenv('RPC_URL_FALLBACK','')
    PRIVATE_KEY      = os.getenv('PRIVATE_KEY')

if not RPC_URL_PRIMARY or not PRIVATE_KEY:
    print("❌ Задайте в .env RPC_URL(_TEST) и PRIVATE_KEY(_TEST).")
    sys.exit(1)

# ------------------------------------------------------------------------------
# 2. Подключение к Web3
# ------------------------------------------------------------------------------
TIMEOUT    = int(os.getenv('WEB3_TIMEOUT','60'))
RECEIPT_TO = int(os.getenv('RECEIPT_TIMEOUT','120'))

def make_web3(url):
    return Web3(Web3.HTTPProvider(url, request_kwargs={'timeout': TIMEOUT}))

w3 = make_web3(RPC_URL_PRIMARY)
if not w3.is_connected() and RPC_URL_FALLBACK:
    print(f"⚠️ Основной RPC не отвечает, переключаюсь на {RPC_URL_FALLBACK}")
    w3 = make_web3(RPC_URL_FALLBACK)
if not w3.is_connected():
    print("❌ Не удалось подключиться ни к одному RPC.")
    sys.exit(1)

acct = w3.eth.account.from_key(PRIVATE_KEY)
print(f"🔑 Ваш адрес (from): {acct.address}")

# ------------------------------------------------------------------------------
# 3. Загрузка ABI и создание контракта
# ------------------------------------------------------------------------------
contract_address = Web3.to_checksum_address(os.getenv('SMART_CONTRACT_ADDRESS'))

# проверка, что на адресе есть код
code = w3.eth.get_code(contract_address)
if not code or code == b'' or code == '0x':
    print(f"❌ По адресу {contract_address} нет контракта.")
    sys.exit(1)

# читаем ABI из compiled.json
with open('../../backend/compiled.json','r') as f:
    compiled = json.load(f)
abi = compiled['contracts']['Contract.sol']['SweepAndWithdrawETH']['abi']
contract = w3.eth.contract(address=contract_address, abi=abi)

# ------------------------------------------------------------------------------
# 4. Проверка прав и баланса
# ------------------------------------------------------------------------------
try:
    owner = contract.functions.owner().call()
except Exception as e:
    print("❌ Не удалось прочитать owner():", e)
    sys.exit(1)

print(f"👑 Owner в контракте: {owner}")
if owner.lower() != acct.address.lower():
    print("❌ Вы должны быть owner, чтобы вызвать withdrawAll().")
    sys.exit(1)

balance = w3.eth.get_balance(contract_address)
print(f"🏦 Баланс контракта: {w3.from_wei(balance,'ether')} ETH")
if balance == 0:
    print("ℹ️ Нет ETH для вывода.")
    sys.exit(0)

# ------------------------------------------------------------------------------
# 5. Симуляция вызова withdrawAll()
# ------------------------------------------------------------------------------
print("🔍 Симулирую withdrawAll() через eth_call…")
try:
    contract.functions.withdrawAll().call({'from': acct.address})
    print("✅ Симуляция прошла, можно отправлять реальную транзакцию.")
except ContractLogicError as err:
    print("❌ Симуляция завершилась ошибкой:", err)
    sys.exit(1)

# ------------------------------------------------------------------------------
# 6. Построение, подпись и отправка транзакции
# ------------------------------------------------------------------------------
nonce     = w3.eth.get_transaction_count(acct.address)
gas_price = w3.eth.gas_price
# динамическая оценка газа
gas_est   = contract.functions.withdrawAll().estimate_gas({'from': acct.address})
gas_limit = int(gas_est * 1.2)  # +20% запас
print(f"⛽ gasPrice: {w3.from_wei(gas_price,'gwei')} gwei, gasLimit: {gas_limit}")

tx = contract.functions.withdrawAll().build_transaction({
    'from':         acct.address,
    'nonce':        nonce,
    'gas':          gas_limit,
    'gasPrice':     gas_price,
})
signed_tx = acct.sign_transaction(tx)

def send_raw(w3_inst, raw):
    try:
        return w3_inst.eth.send_raw_transaction(raw)
    except ReadTimeout:
        if w3_inst.provider.endpoint_uri == RPC_URL_PRIMARY and RPC_URL_FALLBACK:
            print("⚠️ ReadTimeout — переключаюсь на резервный RPC")
            return send_raw(make_web3(RPC_URL_FALLBACK), raw)
        print("❌ Не удалось отправить транзакцию (таймаут).")
        sys.exit(1)

tx_hash = send_raw(w3, signed_tx.raw_transaction)
print("⏳ Tx отправлен:", tx_hash.hex())

try:
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=RECEIPT_TO)
except TimeExhausted:
    print("❌ Транзакция не подтвердилась за время.")
    sys.exit(1)

print(f"✅ Tx подтверждён. Статус: {receipt.status}, потрачено газа: {receipt.gasUsed}")

# ------------------------------------------------------------------------------
# 7. Декодирование события Withdrawn
# ------------------------------------------------------------------------------
events = contract.events.Withdrawn().process_receipt(receipt)
if events:
    args = events[0]['args']
    print(f"📣 Withdrawn — to: {args['to']}, amount: {w3.from_wei(args['amount'],'ether')} ETH")
else:
    print("⚠️ Событие Withdrawn не найдено.")
