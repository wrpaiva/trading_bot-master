# 🤖 Guia do Robô de Trading — para qualquer pessoa entender

Bem-vindo(a)! Este guia ensina, passo a passo, como **ligar o robô** e **usar uma carteira**.
A linguagem é bem simples de propósito. Vá com calma e siga as caixinhas na ordem. 😊

---

## 1. O que é este robô? (a história)

Imagine **duas lojas de figurinhas** na mesma rua: a **Uniswap** e a **Sushiswap**.

Às vezes a mesma figurinha está **mais barata numa loja** e **mais cara na outra**.
Nosso robô fica **de olho nas duas lojas o tempo todo**. Quando ele vê a figurinha barata de um lado
e cara do outro, ele **compra barato e vende caro** no mesmo instante e guarda a diferença. 💰

Esse truque tem um nome chique: **arbitragem**.

> 🧠 **Ideia principal:** comprar num lugar, vender no outro, no mesmo segundo, ganhando a diferença.

---

## 2. ⚠️ A regra de ouro da segurança (LEIA!)

> 🛑 **Este robô é para APRENDER e BRINCAR, com dinheiro DE MENTIRINHA.**
>
> Por padrão, ele **NÃO usa dinheiro de verdade**. Ele roda numa **cópia** da rede Ethereum
> que fica só no seu computador (chamada **"fork"**). É como jogar um videogame de compras:
> tudo parece real, mas as moedas são de brincadeira.
>
> - ✅ Pode brincar à vontade — você **não perde dinheiro real**.
> - ❌ **Nunca** coloque aqui a sua carteira principal com dinheiro de verdade.
> - ❌ **Nunca** mostre a ninguém as suas **12 palavras secretas** (a "senha mágica" da carteira).

Se seguir só isso, você está seguro. Bora! 🚀

---

## 3. Coisas que você precisa instalar (só uma vez)

Peça ajuda a um adulto/pessoa mais experiente se travar aqui. É a parte mais "chata", depois fica fácil.

| O que | Para que serve | Como pegar |
|------|-----------------|-----------|
| **Node.js** (versão 16.14.2) | O motor que roda o robô | https://nodejs.org |
| **Truffle** | Ferramenta que "monta" o contrato | No terminal: `npm i -g truffle` |
| **Ganache** | O Ethereum de mentirinha no seu PC | No terminal: `npm i -g ganache` |
| **Chave da Alchemy** (grátis) | Deixa o robô "copiar" a rede real | Crie conta em https://www.alchemy.com e copie a *API Key* |

> 💡 **Terminal** é aquela telinha preta onde você digita comandos. No Windows procure por "PowerShell",
> no Mac/Linux procure por "Terminal".

---

## 4. Preparar o robô (também só uma vez)

Abra o terminal **dentro da pasta do projeto** e digite:

```bash
npm install
```

Isso baixa as peças que o robô precisa. Espere terminar (pode demorar alguns minutos). ✅

---

## 5. A carteira (MetaMask) — a parte que você perguntou 👛

### Primeiro, a verdade rápida:
- 🦊 **MetaMask** = carteira certa para este robô (rede Ethereum). **Vamos usar ela.**
- 👻 **Phantom** = carteira da rede **Solana**. **Não funciona aqui.** Use a MetaMask.

### De onde vem o "dinheiro" do robô?
Quando você liga o **Ganache**, ele **cria 10 carteiras de brincadeira**, cada uma cheia de moedas falsas.
Cada carteira tem:
- um **endereço** (tipo o número da sua casa), e
- uma **chave privada** (a chavinha que abre aquela casa).

O robô vai usar **uma dessas carteiras**. Você **não precisa** da MetaMask para o robô funcionar —
mas dá para **conectar a MetaMask só para VER o dinheiro de brincadeira**. Vamos fazer isso no Passo 8. 😄

---

## 6. Ligar o Ethereum de mentirinha (Ganache)

No terminal, digite (troque `SUA_CHAVE_ALCHEMY` pela sua chave da Alchemy):

```bash
ganache -f wss://eth-mainnet.alchemyapi.io/v2/SUA_CHAVE_ALCHEMY -m brincar -u 0xdEAD000000000000000042069420694206942069 -p 7545
```

O que cada pedacinho faz, em miudinho:
- `-f ...alchemy...` → faz uma **cópia** da rede Ethereum de verdade (o "fork").
- `-m brincar` → a **senha mágica** (aqui usamos a palavra `brincar`; pode ser qualquer palavra, **é só de teste**).
- `-u 0xdEAD...2069` → "empresta" uma conta cheia de moedas para o robô poder mexer no preço.
- `-p 7545` → a "porta" (o número do canal) onde o Ganache vai atender: **7545**.

✨ **Deixe essa janela do terminal ABERTA.** O Ganache vai mostrar **10 endereços** e **10 chaves privadas**.
**Copie o primeiro endereço** (a primeira linha da lista de *Available Accounts*) — vamos usar já já.

---

## 7. Contar ao robô quem ele é (o arquivo `.env`)

Na pasta do projeto existe um arquivo de exemplo chamado **`.env.example`**.
Faça uma cópia dele e chame a cópia de **`.env`** (sem o `.example`). Abra e preencha assim:

```
ALCHEMY_API_KEY="SUA_CHAVE_ALCHEMY"
ARB_FOR="0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
ARB_AGAINST="0x95aD61b0a150d79219dCF64E1E6Cc01f0B64C4cE"
ACCOUNT="COLE_AQUI_O_PRIMEIRO_ENDERECO_DO_GANACHE"
PRICE_DIFFERENCE=0.50
UNITS=0
GAS_LIMIT=600000
GAS_PRICE=0.0093
```

- `ACCOUNT` = **o endereço que você copiou do Ganache** no passo anterior.
- Os outros valores já vêm prontos (WETH e SHIB são as "figurinhas" que o robô negocia).

> 🔒 O arquivo `.env` guarda seus segredos. **Não mande ele para ninguém** e **não suba para a internet.**

---

## 8. (Opcional, mas legal) Ver o dinheiro na MetaMask 🦊

Quer ver as moedas de brincadeira dentro da MetaMask? Faça isso **com uma MetaMask nova/de teste**,
nunca com a sua principal:

1. Abra a MetaMask → clique no nome da rede em cima → **"Adicionar rede" / "Add network"** → **manual**.
2. Preencha:
   - **Nome:** `Ganache Local`
   - **URL RPC:** `http://127.0.0.1:7545`
   - **ID da cadeia (Chain ID):** `1337`
   - **Moeda:** `ETH`
3. Salve e selecione essa rede.
4. Agora clique em **"Importar conta" / "Import account"** e cole **uma das chaves privadas** que o Ganache mostrou.
5. 🎉 Pronto! A MetaMask vai mostrar o dinheiro **de brincadeira** daquela conta.

> 💡 Note que a MetaMask **não "abre sozinha"** quando o robô roda. Ela serve só para **você enxergar**
> o que está acontecendo. Quem faz o trabalho é o robô, no terminal.
>
> 👻 **Phantom:** de novo, não use aqui — ela é para Solana, não para este projeto.

---

## 9. Montar o contrato do robô

Abra **um novo terminal** (deixe o Ganache rodando no outro!) e digite:

```bash
truffle migrate --reset
```

Isso "instala" o contrato inteligente na sua rede de mentirinha. Espere aparecer que deu certo. ✅

---

## 10. LIGAR O ROBÔ! 🟢

No mesmo terminal do passo 9, digite:

```bash
node ./bot.js
```

Você vai ver a mensagem: **"Waiting for swap event..."** (traduzindo: *"Esperando alguém trocar figurinhas..."*).
O robô agora está **acordado e vigiando** as duas lojas. 👀

---

## 11. Criar uma oportunidade (bagunçar o preço de propósito)

O robô só age quando os preços ficam diferentes. Para **forçar** isso e ver o robô trabalhar,
abra **mais um terminal** e digite:

```bash
node ./scripts/manipulatePrice.js
```

Isso faz uma compra grandona numa das lojas, **mudando o preço** de propósito.
Volte para o terminal do robô: ele vai perceber, calcular o **melhor tamanho de compra** e mostrar
se **vale a pena** (lucro depois dos custos). Se valer, ele faz a jogada e mostra um relatório. 📊

---

## 12. Deu tudo certo? Como saber

No terminal do robô, procure por linhas assim:

- **`Optimal WETH In`** → quanto de moeda o robô decidiu usar (ele calcula o tamanho **ideal**, não um chute).
- **`Net Profit (WETH)`** → o **lucro final** depois dos custos.
  - Se for **positivo** ✅ → o robô achou uma jogada boa.
  - Se for **negativo ou zero** ❌ → não valeu a pena, e o robô **espera a próxima** (isso é o certo!).

> 🧮 **Curiosidade:** o robô usa uma continha de matemática para descobrir o **tamanho perfeito** da compra.
> Comprar de menos ganha pouco; comprar demais estraga o preço. Ele acha o ponto exato. 🎯

---

## 13. Desligar tudo

- Para **parar o robô**: clique no terminal dele e aperte **`Ctrl + C`**.
- Para **desligar o Ganache**: faça o mesmo no terminal do Ganache.

> 🔁 Se quiser brincar de novo do zero: desligue o Ganache, ligue de novo (Passo 6),
> rode `truffle migrate --reset` (Passo 9) e depois `node ./bot.js` (Passo 10).

---

## 14. Deu erro? Soluções rápidas 🩹

| O que apareceu | O que provavelmente é | O que fazer |
|----------------|------------------------|-------------|
| `command not found: ganache` | O Ganache não foi instalado | Rode `npm i -g ganache` |
| O robô não faz nada | Ninguém "trocou figurinhas" ainda | Rode o Passo 11 (`manipulatePrice.js`) |
| `Error ... reserves` | Preço/pool ficou estranho | Desligue o Ganache e recomece do Passo 6 |
| MetaMask não mostra saldo | Rede ou conta errada | Confira a rede `Ganache Local` e reimporte a chave |
| Nada conecta | Ganache foi fechado sem querer | Reabra o Ganache (Passo 6) e deixe aberto |

---

## 15. Palavras difíceis, explicadas fácil 📖

- **Carteira (wallet):** sua "mochila" que guarda moedas digitais.
- **MetaMask:** uma carteira para a rede Ethereum (a que usamos).
- **Phantom:** uma carteira para a rede Solana (**não serve aqui**).
- **12 palavras secretas / seed:** a **senha mestra** da carteira. Quem tem isso, tem tudo. **Nunca compartilhe.**
- **Fork:** uma **cópia** da rede de verdade, só para testar sem risco.
- **Ganache:** o programa que cria essa cópia no seu computador.
- **Contrato inteligente:** um "programinha" que vive dentro da rede e faz as trocas.
- **Gás (gas):** a "taxinha" que se paga para a rede fazer uma operação.
- **Arbitragem:** comprar barato num lugar e vender caro no outro, no mesmo instante.

---

### ✅ Resumo em 5 linhas
1. Instale Node, Truffle, Ganache e pegue a chave da Alchemy.
2. `npm install` na pasta do projeto.
3. Ligue o Ganache (Passo 6) e preencha o `.env` com o endereço dele.
4. `truffle migrate --reset` e depois `node ./bot.js`.
5. `node ./scripts/manipulatePrice.js` para ver o robô em ação. 🎉

Divirta-se aprendendo — e lembre-se: **aqui é tudo dinheiro de brincadeira.** 🧸
