# MohuanLED para Windows

Controle de fitas LED Bluetooth Low Energy (BLE) da linha **MohuanLED / BJ_LED** direto do PC, sem precisar do app Android. Interface simples em Tkinter e comunicação via [`bleak`](https://github.com/hbldh/bleak).

> **Status:** protótipo. O código compila, mas ainda não foi validado com uma fita real. Veja [Limitações](#limitações).

## Recursos

- Busca e conexão com dispositivos `BJ_LED`, `BJ_LED_M`, `BJ_LED_HC` e `BJ_LED_MHC`
- Ligar e desligar
- Cor por sliders R, G, B, brilho e seletor de cor do Windows
- Modos internos da fita com ajuste de velocidade (experimental)
- Efeitos executados no PC: arco-íris, respiração e strobe
- Descoberta automática da característica de escrita BLE

## Requisitos

- Windows 10 ou 11
- Python 3.9 ou superior
- Adaptador Bluetooth **4.0 ou superior (com BLE)**, interno ou USB

## Instalação e uso

```
pip install bleak
python mohuan_led.py
```

1. Ligue o Bluetooth do Windows e feche o app do celular (a fita aceita só uma conexão por vez).
2. Clique em **Buscar**, escolha a fita na lista e clique em **Conectar**.
3. Use os controles de cor, modos e efeitos.

### Gerar um `.exe`

```
pip install pyinstaller
pyinstaller --onefile --noconsole mohuan_led.py
```

O executável fica em `dist/`.

## Adaptadores USB

Funcionam sem configuração extra, desde que o Windows os reconheça como Bluetooth LE.

- Dongles antigos (Bluetooth 2.x/3.0) não suportam BLE.
- Com mais de um adaptador, o Windows usa o padrão do sistema; desative no Gerenciador de Dispositivos o que não quiser usar.
- Se a fita não aparecer, aproxime o adaptador (use uma extensão USB, longe de hubs USB 3.0).

## Protocolo

Os pacotes têm o cabeçalho `69 96`:

| Função | Bytes |
| --- | --- |
| Ligar | `69 96 02 01 01` |
| Desligar | `69 96 02 01 00` |
| Cor | `69 96 05 02 R G B` |
| Modo | `69 96 03 04 <modo> <velocidade>` (experimental) |

O serviço BLE esperado é `0000ee01-0000-1000-8000-00805f9b34fb` e a característica de escrita preferida é `0000ee02-0000-1000-8000-00805f9b34fb`. Se ela não existir, o programa usa outra característica de escrita.

Os comandos foram levantados a partir do repositório [MohuanLED-Bluetooth_LED](https://github.com/Walkercito/MohuanLED-Bluetooth_LED) e da análise do app Android original (`com.kimoji.flutter.bleled`, versão 1.4.6).

## Limitações

- Não testado com hardware real.
- Os números dos modos (0–21) seguem anotações ambíguas do repositório de referência; confira o que cada um faz na sua fita. O mapeamento fica em `Led.mode()`.
- Variantes HC podem usar outra ordem de cores (por exemplo GRB). Se vermelho aparecer verde, ajuste a ordem em `Led.send_rgb()`.
- Os efeitos de arco-íris, respiração e strobe são feitos no PC, enviando uma cor por vez, então dependem da conexão e podem variar em suavidade.
- Ainda não implementado: efeito reativo a som, timers/relógio e grupos de dispositivos do app original.
- O `bleak` no Windows não permite escolher o adaptador Bluetooth.

## Estrutura

```
mohuan_led.py   # aplicativo completo (BLE + interface)
README.md
```

Dentro do arquivo, a classe `Led` cuida do BLE em um loop `asyncio` próprio (em outra thread) e a classe `App` monta a interface; os resultados voltam à interface por uma fila.

## Licença e avisos

Projeto independente, sem relação com a MohuanLED ou com os autores do app original. Use por sua conta e risco.
