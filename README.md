# Lexicon

Linux ve Termux (Android) için modüler, terminal tabanlı sistem monitörü.
Sıfır bağımlılık: yalnızca Python 3.10+ standart kütüphanesi kullanır.

```
 LEXICON  vm · Linux · Ubuntu 24.04 · çekirdek 6.18.44 x86_64
 açık 2g 3s 10dk · yük 0.42 0.31 0.27 · süreç 212 (2 çalışıyor)
── CPU · Intel Xeon @ 2.10GHz · 4 çekirdek ─────────────────────────
Toplam  ████████████░░░░░░░░░░░░░░░░░░░░░░░   31.4%   frekans 2100 MHz
  0 ████████   28.0%    1 ██████████   41.2% ...
── BELLEK ───────────────────────────────────────────────────────────
RAM     ███████████████░░░░░░░░░░░░░░░░░░░   48.2%  3.8 GiB / 7.8 GiB
...
```

## Özellikler

| Modül        | Ne gösterir                                                              |
| ------------ | ------------------------------------------------------------------------ |
| CPU          | Toplam ve çekirdek başına kullanım, frekans, load average, model, geçmiş |
| Bellek       | RAM ve swap, önbellek, geçmiş grafiği                                    |
| Disk         | Bağlama noktaları, doluluk, disk G/Ç hızları (sanal FS'ler elenir)      |
| Ağ           | Arayüz başına anlık ↓/↑ hız, toplam trafik, hata/düşen paket, durum     |
| Süreçler     | PID, ad, durum, CPU%, RSS; CPU / bellek / PID / ad sıralaması, kaydırma  |
| Sıcaklık     | thermal_zone ve hwmon sensörleri (en sıcak 6)                            |
| Pil          | Yüzde ve durum (pil yoksa gizlenir)                                      |
| Uyarılar     | Eşik tabanlı CPU, RAM, swap, disk, sıcaklık ve pil uyarıları             |
| Dışa aktarım | Kararlı şemalı JSON (`--json`), diğer CLI araçları için veri kaynağı     |

## Kurulum

Paket gerektirmez. Depoyu indirip doğrudan çalıştırabilirsiniz:

```sh
python3 -m lexicon             # etkileşimli TUI
```

Kalıcı kurulum için:

```sh
pip install .                  # 'lexicon' komutu eklenir
# Termux'ta:  pkg install python && pip install .
```

Gereksinimler: Python 3.10+. TUI için `curses` gerekir (Linux'ta ve Termux'ta
varsayılan olarak bulunur).

## Kullanım

| Komut                         | Açıklama                                           |
| ----------------------------- | -------------------------------------------------- |
| `lexicon`                     | Etkileşimli TUI (terminal bir TTY değilse otomatik düz metin) |
| `lexicon --once`              | Tek bir rapor yazdır ve çık                        |
| `lexicon --plain --count 5`   | Düz metin akışı, 5 örnek                           |
| `lexicon --json --count 1`    | JSON snapshot (diğer araçlar için)                 |
| `lexicon --doctor`            | Bu ortamda hangi kaynakların okunabildiğini göster |
| `lexicon --sort mem`          | Süreçleri bellek kullanımına göre sırala           |
| `lexicon --interval 2`        | Örnekleme aralığı (saniye)                         |
| `lexicon --config yol.json`   | Belirli bir yapılandırma dosyası                   |

### TUI tuşları

| Tuş            | İşlev                                         |
| -------------- | --------------------------------------------- |
| `q` / `Esc`    | Çıkış                                         |
| `p`            | Duraklat / devam                              |
| `s`            | Sıralamayı değiştir (CPU → BELLEK → PID → AD) |
| `j` / `↓`, `k` / `↑` | Süreç listesinde kaydır                 |
| `PgDn` / `PgUp` | 10'arlı kaydır; `g` / `Home` başa dön        |
| `r`            | Hemen yenile                                  |
| `+` / `-`      | Örnekleme aralığını 0.5 s değiştir            |

## Termux'ta önemli notlar

Android, uygulamaların `/proc` ve `/sys` alanlarını kısıtlar. Lexicon bu
yüzden her kaynağı bağımsız okur: bir kaynak erişilemezse o bölüm "veri yok"
olarak gösterilir ve diğerleri çalışmaya devam eder. Hangi kaynakların
kullanılabildiğini görmek için:

```sh
lexicon --doctor
```

Root gerektirmez; ama sıcaklık sensörleri ve bazı süreç bilgileri Android
sürümüne göre görünmeyebilir.

## Yapılandırma

Varsayılan yol: `$XDG_CONFIG_HOME/lexicon/config.json` (yoksa `~/.config/lexicon/config.json`).
Dosya isteğe bağlıdır; yalnızca değiştirmek istediğiniz anahtarları yazmanız yeterlidir.

```json
{
  "interval": 1.0,
  "history_size": 120,
  "process_limit": 15,
  "sort": "cpu",
  "thresholds": {
    "cpu_warn": 80,
    "cpu_crit": 95,
    "mem_warn": 85,
    "mem_crit": 95,
    "disk_warn": 85,
    "disk_crit": 95,
    "temp_warn": 75,
    "temp_crit": 90,
    "battery_low": 20,
    "battery_crit": 10
  }
}
```

`process_limit`, düz metin ve `--once` çıktılarında gösterilecek süreç sayısıdır.
TUI'de süreç listesi ekrana sığacak kadar gösterilir.

## Mimari

```
lexicon/
├── cli.py               komut satırı, modlar, doctor
├── config.py            yapılandırma yükleme ve doğrulama
├── platform_info.py     Linux / Android / Termux tespiti
├── models.py            Snapshot ve alt veri modelleri (saf dataclass)
├── export.py            JSON şeması (schema=1)
├── collectors/          veri kaynakları — her biri bir Collector
│   ├── base.py          Context, güvenli okuma, DataUnavailable
│   ├── cpu.py  memory.py  disk.py  network.py
│   ├── processes.py  sensors.py  power.py  system.py
├── core/                çekirdek motor
│   ├── engine.py        örnekleme döngüsü, hata izolasyonu, akış
│   ├── history.py       sabit boyutlu geçmiş tamponları
│   └── alerts.py        eşik kuralları (saf fonksiyon)
└── ui/                  sunum katmanı (I/O'suz düzen mantığı)
    ├── dashboard.py     Snapshot → satır (Seg listesi); saf fonksiyonlar
    ├── format.py        bayt, hız, süre, çubuk, sparkline, glyph seti
    ├── curses_app.py    etkileşimli TUI
    └── plain.py         düz metin çıktısı
```

Tasarım ilkeleri:

- **Katmanlar birbirini bilmez.** Collector'lar ekran çizmez; UI yalnızca
  model okur. Yeni bir veri kaynağı için `Collector` türetip
  `collectors/__init__.py` içindeki listeye eklemek yeterlidir.
- **Hata izolasyonu.** Bir kaynağın hatası diğerlerini etkilemez; hata
  `Snapshot.errors` içinde raporlanır.
- **Test edilebilir kökler.** `LEXICON_PROC`, `LEXICON_SYS`, `LEXICON_ETC`
  ortam değişkenleri kök dizinleri değiştirir. Testler sahte bir `/proc`
  ağacı üzerinde çalışır.
- **Hız hesapları durumludur.** CPU, ağ, disk ve süreç collector'ları önceki
  örneği tutar; ilk örnek yalnızca referans noktasıdır (`Engine.prime`).

Yeni bir collector eklemek:

```python
# lexicon/collectors/gpu.py
from .base import Collector, Context, DataUnavailable, read_text

class GpuCollector(Collector):
    name = "gpu"

    def collect(self, ctx: Context):
        text = read_text(ctx.sys / "class/drm/card0/device/gpu_busy_percent")
        if text is None:
            raise DataUnavailable("GPU sayaçları yok")
        return int(text)
```

Ardından `models.py` içine bir alan, `Engine.sample` içine bir eşleme ve
`ui/dashboard.py` içine bir bölüm eklemeniz gerekir.

## Testler

```sh
python3 -m unittest discover -s tests -t .
```

Testler ayrıştırıcıları, sahte bir `/proc` ağacı üzerindeki collector'ları,
uyarı kurallarını, yapılandırma doğrulamasını ve render çıktısını kapsar.

## Lisans

MIT
