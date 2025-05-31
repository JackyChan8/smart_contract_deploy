import os
import json

from web3 import Web3
from dotenv import load_dotenv
from web3.exceptions import TimeExhausted
from requests.exceptions import ReadTimeout
from solcx import compile_standard, install_solc


class SmartContract:
    """
        Генерация Смарт Контракта
    """
    def __init__(self):
        self.solidity_version = '0.8.20'
        self.compile_path     = './compile/compiled.json'
        self.contract_path    = './contracts/Contract.sol'

    def load_env(self) -> None:
        """
            Получения Переменных из .env
        """
        IS_TEST = os.getenv('IS_TEST')
        if IS_TEST:
            self.RPC_URL_PRIMARY   = os.getenv('RPC_URL_TEST')
            self.RPC_URL_FALLBACK  = os.getenv('RPC_URL_TEST_FALLBACK', '')
            self.PRIVATE_KEY       = os.getenv('PRIVATE_KEY_TEST')
        else:
            self.RPC_URL_PRIMARY   = os.getenv('RPC_URL')
            self.RPC_URL_FALLBACK  = os.getenv('RPC_URL_FALLBACK', '')
            self.PRIVATE_KEY       = os.getenv('PRIVATE_KEY')

        self.TIMEOUT    = int(os.getenv('WEB3_TIMEOUT', '60'))
        self.RECEIPT_TO = int(os.getenv('RECEIPT_TIMEOUT', '120'))

        if not self.RPC_URL_PRIMARY or not self.PRIVATE_KEY:
            raise SystemExit("❌ В переменных окружения не заданы RPC_URL и/или PRIVATE_KEY.")
        print('✅ Переменное окружение успешно загружено')

    def connect_web3(self) -> None:
        """
            Подключение к Web3
        """
        self.w3 = Web3(
            Web3.HTTPProvider(
                self.RPC_URL_PRIMARY,
                request_kwargs={'timeout': self.TIMEOUT},
            )
        )
        if not self.w3.is_connected():
            raise SystemExit("❌ Не удалось подключиться ни к одному RPC.")
        print('✅ Подключение к Web3 успешно выполнено')

    def compile(self) -> None:
        """
            Компиляция Смарт Контракта
        """
        try:
            install_solc(self.solidity_version)

            with open(self.contract_path, 'r') as f:
                source_code = f.read()
            
            compiled = compile_standard(
                {
                    "language": "Solidity",
                    "sources": {
                        "Contract.sol": {
                            "content": source_code
                        }
                    },
                    "settings": {
                        "outputSelection": {
                            "*": {
                                "*": ["abi", "evm.bytecode"]
                            }
                        }
                    }
                },
                solc_version='0.8.20'
            )

            with open(self.compile_path, 'w') as f:
                json.dump(compiled, f)

            print('✅ Компиляция успешно сохранена в compiled.json')
        except Exception as e:
            raise SystemExit(f'❌ Произошла ошибка при компиляции. Ошибка: {e}')

    def send_raw(self, w3_inst: Web3, raw: bytes):
        """
            Отправка с fallback на резервный RPC
        """
        try:
            return w3_inst.eth.send_raw_transaction(raw)
        except ReadTimeout:
            if w3_inst.provider.endpoint_uri == self.RPC_URL_PRIMARY and self.RPC_URL_FALLBACK:
                print("⚠️ ReadTimeout на основном RPC, пробую резервный…")
                return self.send_raw(
                    Web3(Web3.HTTPProvider(self.RPC_URL_FALLBACK, request_kwargs={'timeout': self.TIMEOUT})),
                    raw
                )
            raise SystemExit(f'❌ Не удалось отправить транзакцию (таймаут).')

    def deploy(self):
        """
            Загрузка Смарт Контракта в Сеть
        """
        try:

            acct = self.w3.eth.account.from_key(self.PRIVATE_KEY)
            print(f"🔑 Владелец: {acct.address}")

            # ABI и байткод
            with open(self.compile_path, 'r') as f:
                compiled = json.load(f)
            
            contract_data = compiled['contracts']['Contract.sol']['SweepAndWithdrawETH']
            abi           = contract_data['abi']
            bytecode      = contract_data['evm']['bytecode']['object']

            # Готовим контракт-объект для деплоя
            Contract = self.w3.eth.contract(abi=abi, bytecode=bytecode)

            # Динамическая оценка газа
            nonce      = self.w3.eth.get_transaction_count(acct.address)
            gas_price  = self.w3.eth.gas_price  # или w3.to_wei('5','gwei')
            print("⛽ Текущий gasPrice:", self.w3.from_wei(gas_price, 'gwei'), "gwei")

            gas_est = Contract.constructor().estimate_gas({'from': acct.address})
            gas_limit = int(gas_est * 1.2)  # +20% запаса
            print(f"📊 Оценка газа: {gas_est}, выставляем gas_limit = {gas_limit}")

            # Строим и подписываем транзакцию
            tx = Contract.constructor().build_transaction({
                'from':      acct.address,
                'nonce':     nonce,
                'gas':       gas_limit,
                'gasPrice':  gas_price,
                # для EIP-1559 вместо gasPrice можно указать:
                # 'maxPriorityFeePerGas': …,
                # 'maxFeePerGas': …,
                # 'type': '0x2'
            })

            signed = acct.sign_transaction(tx)
            tx_hash = self.send_raw(self.w3, signed.raw_transaction)
            print("⏳ TxHash:", tx_hash.hex())

            # Ожидание майнинга
            try:
                receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=self.RECEIPT_TO)
            except TimeExhausted:
                raise SystemExit("❌ Транзакция не подтвердилась за время.")
            
            print(f"✅ Контракт задеплоен! Адрес: {receipt.contractAddress}")
            print(f"Потрачено газа: {receipt.gasUsed}")

            with open('contract_into.txt', 'a', encoding='utf-8') as f:
                f.write(f'Адрес Контракта: {receipt.contractAddress}')
        except Exception as e:
            raise SystemExit(f'❌ Произошла ошибка при загрузки смарт контракта в сеть. Ошибка: {e}')

    def run(self):
        """
            Запуск
        """
        # 1. Подключение Переменного Окружения
        self.load_env()

        # 2. Подключение к Web3
        self.connect_web3()

        # 3. Компиляция
        self.compile()

        # 4. Деплой
        self.deploy()


if __name__ == '__main__':
    load_dotenv()

    smart_contract = SmartContract()
    smart_contract.run()
