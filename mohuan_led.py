"""MohuanLED para Windows - controle BLE de fitas LED BJ_LED*.

Requisitos: Python 3.9+ e `pip install bleak`
Execute:    python mohuan_led.py

Protocolo (cabecalho 69 96), baseado no repo MohuanLED-Bluetooth_LED:
  ligar 69 96 06 01 01 (e/ou 69 96 02 01 01) | desligar 69 96 02 01 00
  cor   69 96 05 02 R G B
  modo  69 96 03 <banco> <modo> <velocidade>
        banco 3: modos 0-21 | banco 4: modos 0-9 | velocidade 1 (rapido) a 10 (lento)
"""
import asyncio
import colorsys
import math
import queue
import threading
import tkinter as tk
from tkinter import colorchooser, ttk

from bleak import BleakClient, BleakScanner

PREFIX = "BJ_LED"  # BJ_LED, BJ_LED_M, BJ_LED_HC, BJ_LED_MHC
PREFERRED_CHAR = "0000ee02-0000-1000-8000-00805f9b34fb"
ON_A = bytes.fromhex("6996060101")  # usado pelo repo 8none1/bj_led
ON_B = bytes.fromhex("6996020101")  # usado pelo repo MohuanLED-Bluetooth_LED (BJ_LED_M)
OFF = bytes.fromhex("6996020100")


class Led:
    """Fala BLE num loop asyncio proprio; a UI recebe resultados por fila."""

    def __init__(self, events: queue.Queue):
        self.events = events
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        self.client = None
        self.char = None
        self.rgb = (255, 255, 255)
        self.brightness = 255
        self._task = None
        self._sending = False

    # ---- infraestrutura -------------------------------------------------
    def submit(self, coro, tag):
        async def wrapper():
            try:
                self.events.put((tag, await coro, None))
            except Exception as e:  # noqa: BLE001
                self.events.put((tag, None, e))

        asyncio.run_coroutine_threadsafe(wrapper(), self.loop)

    async def _cancel_effect(self):
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._task = None

    # ---- conexao --------------------------------------------------------
    async def scan(self, show_all):
        found = await BleakScanner.discover(timeout=5, return_adv=True)
        out = []
        for addr, (dev, adv) in found.items():
            name = adv.local_name or dev.name or ""
            if show_all or name.startswith(PREFIX):
                out.append((name or "(sem nome)", addr))
        return out

    async def connect(self, addr):
        await self.disconnect()
        client = BleakClient(addr)
        await client.connect()
        chars = [c for s in client.services for c in s.characteristics]
        writable = [c for c in chars
                    if {"write", "write-without-response"} & set(c.properties)]
        char = (next((c for c in chars if c.uuid.lower() == PREFERRED_CHAR), None)
                or next((c for c in writable if c.service_uuid.lower().startswith("0000ee")), None)
                or (writable[0] if writable else None))
        if char is None:
            await client.disconnect()
            raise RuntimeError("Nenhuma caracteristica de escrita encontrada")
        self.client, self.char = client, char
        return char.uuid

    async def disconnect(self):
        await self._cancel_effect()
        if self.client and self.client.is_connected:
            await self.client.disconnect()
        self.client = self.char = None

    async def write(self, data: bytes):
        if not (self.client and self.client.is_connected):
            raise RuntimeError("Desconectado")
        resp = "write-without-response" not in self.char.properties
        await self.client.write_gatt_char(self.char, data, response=resp)

    # ---- comandos -------------------------------------------------------
    async def power(self, on: bool):
        await self._cancel_effect()
        if on:
            await self.write(ON_A)
            await asyncio.sleep(0.1)
            await self.write(ON_B)
        else:
            await self.write(OFF)

    async def send_rgb(self, r, g, b, brightness=255):
        k = brightness / 255
        await self.write(bytes([0x69, 0x96, 0x05, 0x02, int(r * k), int(g * k), int(b * k)]))

    async def mode(self, bank, mode, speed):
        await self._cancel_effect()
        await self.write(bytes([0x69, 0x96, 0x03, bank, mode, speed]))

    def push_color(self, rgb, brightness):
        """Chamado pela UI (qualquer thread); junta movimentos rapidos do slider."""
        self.rgb, self.brightness = rgb, brightness
        if not self._sending:
            self._sending = True
            asyncio.run_coroutine_threadsafe(self._flush(), self.loop)

    async def _flush(self):
        try:
            await self._cancel_effect()
            last = None
            while last != (self.rgb, self.brightness):
                last = (self.rgb, self.brightness)
                await self.send_rgb(*last[0], last[1])
        except Exception as e:  # noqa: BLE001
            self.events.put(("err", None, e))
        finally:
            self._sending = False

    # ---- efeitos (feitos no PC, cor a cor) ------------------------------
    def effect(self, name):
        asyncio.run_coroutine_threadsafe(self._start_effect(name), self.loop)

    def stop_effect(self):
        asyncio.run_coroutine_threadsafe(self._cancel_effect(), self.loop)

    async def _start_effect(self, name):
        await self._cancel_effect()
        fn = {"rainbow": self._rainbow, "breathing": self._breathing,
              "strobe": self._strobe}[name]

        async def guarded():
            try:
                await fn()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                self.events.put(("err", None, e))

        self._task = asyncio.ensure_future(guarded())

    async def _rainbow(self):
        h = 0.0
        while True:
            r, g, b = (int(x * 255) for x in colorsys.hsv_to_rgb(h, 1, 1))
            await self.send_rgb(r, g, b, self.brightness)
            h = (h + 0.01) % 1
            await asyncio.sleep(0.05)

    async def _breathing(self):
        t = 0.0
        while True:
            v = (1 - math.cos(t)) / 2
            await self.send_rgb(*self.rgb, int(self.brightness * v))
            t += 0.12
            await asyncio.sleep(0.04)

    async def _strobe(self):
        while True:
            await self.send_rgb(*self.rgb, self.brightness)
            await asyncio.sleep(0.12)
            await self.send_rgb(0, 0, 0)
            await asyncio.sleep(0.12)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("MohuanLED")
        self.resizable(False, False)
        self.events = queue.Queue()
        self.led = Led(self.events)
        self.devices = {}
        self.show_all = tk.BooleanVar(value=False)
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(50, self._poll)

    def _build(self):
        pad = {"padx": 8, "pady": 4}
        top = ttk.Frame(self)
        top.pack(fill="x", **pad)
        self.combo = ttk.Combobox(top, state="readonly", width=34)
        self.combo.pack(side="left")
        ttk.Button(top, text="Buscar", command=self._scan).pack(side="left", padx=4)
        ttk.Button(top, text="Conectar", command=self._connect).pack(side="left")
        ttk.Checkbutton(self, text="Mostrar todos os dispositivos",
                        variable=self.show_all).pack(anchor="w", padx=8)

        row = ttk.Frame(self)
        row.pack(fill="x", **pad)
        ttk.Button(row, text="Ligar", command=lambda: self._run(self.led.power(True))).pack(side="left")
        ttk.Button(row, text="Desligar", command=lambda: self._run(self.led.power(False))).pack(side="left", padx=4)

        box = ttk.LabelFrame(self, text="Cor")
        box.pack(fill="x", **pad)
        self.vars = {}
        for name, to in (("R", 255), ("G", 255), ("B", 255), ("Brilho", 255)):
            f = ttk.Frame(box)
            f.pack(fill="x")
            ttk.Label(f, text=name, width=6).pack(side="left")
            v = tk.IntVar(value=255 if name != "Brilho" else 255)
            self.vars[name] = v
            tk.Scale(f, from_=0, to=to, orient="horizontal", length=280,
                     variable=v, command=lambda _=None: self._color()).pack(side="left")
        self.preview = tk.Canvas(box, width=40, height=24, highlightthickness=1)
        self.preview.pack(side="left", padx=8, pady=4)
        ttk.Button(box, text="Escolher cor...", command=self._pick).pack(side="left")

        mbox = ttk.LabelFrame(self, text="Modos da fita (experimental)")
        mbox.pack(fill="x", **pad)
        self.bank_v = tk.IntVar(value=3)
        self.mode_v = tk.IntVar(value=0)
        self.speed_v = tk.IntVar(value=5)
        ttk.Label(mbox, text="Banco (3: modos 0-21 | 4: modos 0-9)").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(mbox, from_=3, to=4, width=5, textvariable=self.bank_v).grid(row=0, column=1)
        ttk.Label(mbox, text="Modo").grid(row=1, column=0, sticky="w")
        ttk.Spinbox(mbox, from_=0, to=21, width=5, textvariable=self.mode_v).grid(row=1, column=1)
        ttk.Label(mbox, text="Velocidade (1 rapido - 10 lento)").grid(row=2, column=0, sticky="w")
        ttk.Spinbox(mbox, from_=1, to=10, width=5, textvariable=self.speed_v).grid(row=2, column=1)
        ttk.Button(mbox, text="Aplicar", command=self._mode).grid(row=0, column=2, rowspan=3, padx=8)

        ebox = ttk.LabelFrame(self, text="Efeitos (no PC)")
        ebox.pack(fill="x", **pad)
        for text, key in (("Arco-iris", "rainbow"), ("Respiracao", "breathing"), ("Strobe", "strobe")):
            ttk.Button(ebox, text=text, command=lambda k=key: self.led.effect(k)).pack(side="left", padx=2, pady=4)
        ttk.Button(ebox, text="Parar", command=self.led.stop_effect).pack(side="left", padx=2)

        self.status = ttk.Label(self, text="Pronto. Clique em Buscar.", anchor="w")
        self.status.pack(fill="x", padx=8, pady=6)
        self._color(send=False)

    # ---- acoes ----------------------------------------------------------
    def _run(self, coro):
        self.led.submit(coro, "cmd")

    def _scan(self):
        self.status.config(text="Buscando (5 s)...")
        self.led.submit(self.led.scan(self.show_all.get()), "scan")

    def _connect(self):
        label = self.combo.get()
        if label not in self.devices:
            self.status.config(text="Selecione um dispositivo.")
            return
        self.status.config(text="Conectando...")
        self.led.submit(self.led.connect(self.devices[label]), "connect")

    def _color(self, send=True):
        r, g, b = (self.vars[k].get() for k in "RGB")
        self.preview.config(bg=f"#{r:02x}{g:02x}{b:02x}")
        if send and self.led.client:
            self.led.push_color((r, g, b), self.vars["Brilho"].get())

    def _pick(self):
        rgb, _ = colorchooser.askcolor(color=self.preview["bg"])
        if rgb:
            for k, val in zip("RGB", rgb):
                self.vars[k].set(int(val))
            self._color()

    def _mode(self):
        bank = self.bank_v.get()
        mode = min(self.mode_v.get(), 9 if bank == 4 else 21)
        self._run(self.led.mode(bank, mode, self.speed_v.get()))

    def _poll(self):
        while True:
            try:
                tag, res, err = self.events.get_nowait()
            except queue.Empty:
                break
            if err:
                self.status.config(text=f"Erro: {err}")
            elif tag == "scan":
                self.devices = {f"{n} [{a}]": a for n, a in res}
                self.combo["values"] = list(self.devices)
                if self.devices:
                    self.combo.current(0)
                self.status.config(text=f"{len(res)} dispositivo(s) encontrado(s).")
            elif tag == "connect":
                self.status.config(text=f"Conectado (caracteristica {res}).")
        self.after(50, self._poll)

    def _close(self):
        self.led.submit(self.led.disconnect(), "bye")
        self.after(300, self.destroy)


if __name__ == "__main__":
    try:  # nitidez em telas HiDPI no Windows
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001
        pass
    App().mainloop()
