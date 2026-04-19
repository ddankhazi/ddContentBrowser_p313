# Multithreaded Thumbnail Generation

## Áttekintés

A ddContentBrowser most **hibrid multithreaded thumbnail generálást** használ a jobb teljesítmény érdekében.

## Architektúra

### Előző megoldás (Single-threaded)
- 1 háttérszál dolgozta fel sorban a thumbnailokat
- Lassú volt nagy fájloknál vagy sok thumbnail esetén

### Új megoldás (Hybrid Multithreaded)

**Két-szintű párhuzamosítás:**

1. **ThreadPoolExecutor (Worker Threads)**
   - CPU-intenzív munka: dekódolás, resizing, color space konverzió
   - Alapértelmezett: 3 worker thread (párhuzamosan dolgoznak)
   - Numpy array-ket generálnak (thread-safe)

2. **Main QThread**
   - QPixmap konverzió (KELL a Qt thread-safety miatt)
   - Signal emittálás a UI felé
   - Cache kezelés

### Miért biztonságos?

✅ **Qt objektumok (QPixmap, QImage) csak a main thread-ben jönnek létre**
- A worker threads csak numpy array-ket készítenek
- A main QThread konvertálja őket QPixmap-pé

✅ **Thread-safe queue kommunikáció**
- Worker threads → Result Queue → Main Thread
- Nincs race condition

✅ **Futures kezelés**
- Nyomon követjük az aktív job-okat
- Nem töltünk be duplikált fájlokat

## Támogatott formátumok

Az összes formátum párhuzamosan generálódik:

- **Képek**: JPG, PNG, TIFF, TGA, BMP, WebP, GIF
- **HDR formátumok**: HDR, EXR
- **PSD fájlok**: Adobe Photoshop
- **Videók**: MP4, MOV, AVI, MKV, WebM (első frame)
- **Textures**: TX (OpenImageIO)
- **Dokumentumok**: PDF (első oldal)

## Beállítások

### Worker Threads száma

A `settings.json` fájlban:

```json
{
  "thumbnails": {
    "worker_threads": 3
  }
}
```

**Ajánlott értékek:**
- **2-4 cores CPU**: 2-3 workers
- **6-8 cores CPU**: 3-4 workers  
- **8+ cores CPU**: 4-5 workers

⚠️ **Figyelem**: Túl sok worker (>6) növelheti a memory használatot és I/O versenyt okozhat.

## Teljesítmény

### Tesztelési eredmények (várható)

**Példa: 100 thumbnail generálása (8K TIFF fájlok)**

| Konfiguráció | Idő | Gyorsulás |
|--------------|------|-----------|
| 1 thread (régi) | ~45s | 1.0x |
| 2 workers | ~25s | 1.8x |
| 3 workers | ~18s | 2.5x |
| 4 workers | ~15s | 3.0x |

*Eredmények CPU-tól és SSD sebességétől függnek*

### Mikor látható a legnagyobb javulás?

✅ **Nagy fájlok**: 8K/16K TIFF, HDR, EXR
✅ **Sok thumbnail egyszerre**: directory váltáskor
✅ **CPU-intenzív formátumok**: PSD, EXR tone mapping
✅ **Gyors SSD**: NVMe SSD-n nagyobb a javulás

⚠️ **Kisebb javulás várható:**
- Lassú HDD (I/O bottleneck)
- Kis fájlok (JPG, PNG < 1MB)
- Cache találatok esetén (nincs generálás)

## Technikai részletek

### Worker Thread Job Flow

```
1. Main Thread: Új fájl → Queue-ba
2. Main Thread: Submit job → ThreadPoolExecutor
3. Worker Thread: Fájl betöltése (OpenCV/PIL/imageio)
4. Worker Thread: Resizing + color konverzió
5. Worker Thread: Numpy array → Result Queue
6. Main Thread: Result Queue → numpy_to_pixmap()
7. Main Thread: QPixmap → Cache + Signal emit
```

### Memory Management

- **Max in-flight jobs**: `max_workers × 2`
  - Korlátozza az egyidejű betöltött képeket
  - Megelőzi a memory túlcsordulást

- **Queue limit**: Nincs hard limit
  - De csak `max_workers × 2` processzálódik egyszerre

### Thread Safety

**Biztonságos:**
✅ numpy array műveletek (dekódolás, resizing)
✅ OpenCV, PIL, imageio (thread-safe olvasás)
✅ Queue kommunikáció (Python Queue thread-safe)

**NEM thread-safe (ezért main thread-ben van):**
❌ QPixmap, QImage létrehozás
❌ Qt Signal emittálás
❌ Disk cache írás/olvasás

## Hibakezelés

### Worker thread hiba
- Exception a worker-ben → Result Queue-ba kerül error flag-gel
- Main thread emit `generation_failed` signal-t
- UI-ban default icon jelenik meg

### Shutdown
- `stop()` meghívásakor:
  1. `is_running = False`
  2. Queue törlése
  3. ThreadPoolExecutor shutdown (wait=True)
  4. Futó job-ok befejezése

## Changelog

### 2025-12-10
- ✨ Implementálva hybrid multithreaded thumbnail generation
- ✨ ThreadPoolExecutor 3 worker thread-del (konfigurálható)
- ✨ Thread-safe numpy array pipeline
- ✨ Worker threads számának beállítása settings.json-ban
- 🔒 Qt thread-safety biztosítva (QPixmap csak main thread-ben)

## Tesztelés

### Manual Testing
1. Nyiss meg egy mappát sok nagy fájllal (TIFF, EXR)
2. Figyeld a thumbnail generálás sebességét
3. Ellenőrizd Task Manager-ben a CPU kihasználtságot
   - Láthatóan több core dolgozik
4. Váltogass nézetek között (grid ↔ list)

### Performance Testing
```python
# Debug módban látható a worker thread aktivitás
DEBUG_MODE = True  # cache.py elején
```

Log output:
```
[ThumbnailGenerator] Initialized with 3 worker threads
[CACHE-THREAD] Processing: texture_8k.tif
[CACHE-THREAD] → Submitting to worker pool...
[WORKER] Processing in thread: ThumbWorker-1
```

## FAQ

**Q: Biztonságos Qt-vel?**  
A: Igen, a QPixmap objektumok csak a main thread-ben jönnek létre. A worker threads csak numpy array-ket készítenek.

**Q: Milyen CPU-t érdemes használni?**  
A: 4+ cores CPU ajánlott. 2 cores-on kisebb a javulás.

**Q: Növeli a memory használatot?**  
A: Igen, kis mértékben. Max `worker_threads × 2` kép van betöltve egyszerre.

**Q: Visszaállítható az eredeti single-thread mód?**  
A: Igen, állítsd be: `"worker_threads": 1` a settings.json-ban.

**Q: Működik hot reload után?**  
A: Igen, a worker pool újraindul minden alkalommal.

## Future Improvements

- [ ] Auto-detect optimal worker count (CPU cores alapján)
- [ ] Priority queue (látható thumbnailok előre)
- [ ] Cancelable jobs (scroll közben)
- [ ] Per-format worker pools (EXR külön pool?)
- [ ] GPU acceleration (OpenCL/CUDA resizing)
