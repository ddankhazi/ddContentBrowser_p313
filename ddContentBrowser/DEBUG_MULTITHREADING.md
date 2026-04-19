# Debug Info - Multithreading

## ✅ Változtatások (2025-12-10)

### 1. Settings Panel - Worker Threads beállítás hozzáadva

**Hol található:**
- Settings → Thumbnails tab → "Performance (Multithreading)" section

**Beállítás:**
- Slider: 1-6 worker threads
- Default: 3 workers
- Tooltip: Részletes magyarázat + ajánlások CPU core count alapján

### 2. Debug Printelés BEKAPCSOLVA

**cache.py:**
```python
DEBUG_MODE = True  # ✨ ENABLED
```

**Mit fog kiírni:**

#### Inicializáláskor (mindig):
```
[ThumbnailGenerator] ✨ Initialized with 3 worker threads
[ThumbnailGenerator]    Thumbnail size: 256px
[ThumbnailGenerator]    JPEG quality: 85
[ThumbnailGenerator]    Debug mode: ENABLED
```

#### Thumbnail generálás közben (DEBUG_MODE = True esetén):
```
[CACHE-THREAD] Processing: texture_8k.tif
[CACHE-THREAD] → Submitting to worker pool...
[CACHE-THREAD] ⚡ Worker job submitted (active jobs: 2)
[ThumbWorker-0] 🔧 Processing: texture_8k.tif (.tif)
[ThumbWorker-0] ✓ Worker completed: texture_8k.tif
```

#### Threadnevek:
- `CACHE-THREAD` - Main QThread (dispatcher)
- `ThumbWorker-0`, `ThumbWorker-1`, `ThumbWorker-2` - Worker threads

### 3. Default Settings frissítve

**settings.json-ban** (auto-generálódik):
```json
{
  "thumbnails": {
    "worker_threads": 3
  }
}
```

## 🧪 Tesztelés

### 1. Indítsd el a böngészőt
```bash
python ddContentBrowser/launch_browser.py
```

### 2. Konzol output ellenőrzése
Látnod kell:
```
[ThumbnailGenerator] ✨ Initialized with 3 worker threads
```

### 3. Nyiss meg egy mappát sok képpel
Látnod kell:
```
[CACHE-THREAD] Processing: file1.jpg
[CACHE-THREAD] ⚡ Worker job submitted (active jobs: 1)
[ThumbWorker-0] 🔧 Processing: file1.jpg (.jpg)
[ThumbWorker-0] ✓ Worker completed: file1.jpg
```

### 4. Ellenőrizd a Settings panelt
1. Settings → Thumbnails tab
2. Görgess le a "Performance (Multithreading)" sectionhöz
3. Látni kell a "Parallel Worker Threads" slidert

### 5. Task Manager ellenőrzés
- Nyisd meg Task Manager-t
- Performance → CPU
- Több mag/thread dolgozik egyidejűleg

## ⚠️ Ha nem látod a gyorsulást

### Lehetséges okok:

1. **Cache találat**
   - A thumbnailek már generálva vannak → cache-ből jönnek
   - Megoldás: Clear Cache (Settings panel)

2. **Kis fájlok**
   - JPG/PNG < 1MB → nagyon gyors egyedül is
   - Tesztelj nagy TIFF/EXR fájlokkal (8K+)

3. **Lassú HDD**
   - I/O bottleneck → több thread sem gyorsít
   - Ellenőrizd: SSD vagy HDD?

4. **Worker threads = 1**
   - Single-threaded mode
   - Ellenőrizd Settings → Thumbnails → Worker Threads

5. **Kevés CPU core**
   - 2 cores CPU-n kevesebb a javulás
   - Ellenőrizd Task Manager → Performance → CPU

## 📊 Teljesítmény mérés

### Manual teszt:
1. Clear cache
2. Állítsd be worker_threads = 1 (Settings)
3. Restart browser
4. Nyiss meg egy mappát → mérj időt
5. Állítsd be worker_threads = 3
6. Restart browser
7. Clear cache
8. Nyiss meg ugyanazt a mappát → mérj időt

### Automatikus teszt:
```bash
python test_multithreaded_thumbnails.py
```

## 🐛 Debug Output kikapcsolása

Ha túl sok a print:
```python
# cache.py
DEBUG_MODE = False  # Kikapcsol minden debug print-et
```

Az inicializálás print mindig látszik (DEBUG_MODE-tól függetlenül).

## 💡 Ajánlott beállítások

### Gaming PC (8+ cores):
```json
{"worker_threads": 4}
```

### Workstation (6-8 cores):
```json
{"worker_threads": 3}
```

### Laptop (4 cores):
```json
{"worker_threads": 2}
```

### Old PC (2 cores):
```json
{"worker_threads": 1}
```

## 🔧 Troubleshooting

### "No speedup at all"
1. Check console: látod a worker thread neveket?
2. Check Task Manager: több mag dolgozik?
3. Check cache: Clear cache és próbáld újra
4. Check file size: nagy fájlok (>5MB)?

### "Slower than before"
1. Csökkentsd worker_threads-et (Settings)
2. Lehet I/O bottleneck (HDD)
3. Lehet túl sok thread (>6)

### "Console spam"
```python
DEBUG_MODE = False  # cache.py-ban
```

### "Setting nem jelenik meg"
1. Restart browser
2. Check settings.json létezik?
   - Hely: `~/.ddContentBrowser/settings.json`
3. Delete settings.json és restart (újra generálódik)
