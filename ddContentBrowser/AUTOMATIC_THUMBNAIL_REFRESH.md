# Automatikus Thumbnail Refresh Rendszer

## Leírás

A DD Content Browser most már **automatikusan frissíti** a thumbnailek megjelenítésekor, ha az eredeti fájlok módosultak.

## Hogyan működik?

### 1. **Automatikus Detektálás**
Az `request_thumbnails_for_visible_items()` metódusban, amikor egy item thumbnail-jét keresünk:

- Ellenőrizzük, hogy az item **memory cache**-ben van-e (gyors, lemez I/O nélkül)
- Ha nincs a memory cache-ben, meghívjuk az `disk_cache.needs_refresh()` metódust
- Ez a metódus ellenőrzi:
  - Van-e a fájlhoz cached thumbnail?
  - Ha van, összevetjük a **fájl módosítási dátumát** (**modified_time**) a **cache generálási dátumával**

### 2. **Frissítés Szükségessége**
A `ThumbnailDiskCache.needs_refresh()` metódus `True`-t ad vissza ha:
- A fájlhoz **nincs** cached thumbnail
- A fájl **módosult** az utolsó generálás óta

### 3. **Automatikus Újragenerálás**
Ha szükséges a frissítés:
- Az item a **regenerálási sorba** kerül
- A thumbnail generátor **előnyfoglalt feldolgozza** a látható itemeket
- Az új thumbnail automatikusan megjelenik az UI-ban

## Implementációs Részletek

### Módosított Fájlok

#### 1. `cache.py`
**Új metódus:** `ThumbnailDiskCache.needs_refresh(file_path, file_mtime)`

```python
def needs_refresh(self, file_path, file_mtime):
    """
    Check if cached thumbnail needs to be refreshed.
    Returns True if:
    - File doesn't have a cached thumbnail
    - File was modified after the thumbnail was generated
    """
```

**Logika:**
- Lekérdezi a cache kulcsot az aktuális `file_mtime`-nal
- Ha a cached thumbnail nem létezik → `True` (frissítés szükséges)
- Ha létezik → `False` (cache érvényes)

#### 2. `browser.py`
**Módosított metódus:** `request_thumbnails_for_visible_items()`

**Korábbi logika (manuális refresh):**
```python
# Csak a disk cache-t néztelek
cached_from_disk = self.disk_cache.get(...)
if cached_from_disk is None:
    # Rajta add a queue-hez
```

**Új logika (automatikus refresh):**
```python
# AUTOMATIC REFRESH: Check if file was modified
needs_refresh = self.disk_cache.needs_refresh(file_path_str, asset.modified_time)

if needs_refresh:
    # Add to queue for regeneration
    visible_items.append(...)
else:
    # Cache is valid, use it
    cached_from_disk = self.disk_cache.get(...)
```

## Cache Key Mechanizmus

A cache kulcs az `asset.modified_time`-t tartalmazza:

```
cache_key = MD5(file_path + "_" + file_mtime)
```

**Ezért működik az automatikus detektálás:**
1. Ha módosul a fájl → `modified_time` megváltozik
2. Új cache kulcsot hoz létre
3. Az új kulccsal a régi cached thumbnail **nem található**
4. `needs_refresh()` → `True`
5. Automatikusan újragenerálódik

## Felhasználói Élmény

### Eset 1: Fájl módosult
1. User másolja fel a módosított képet
2. A browser **automatikusan** frissíti a thumbnail-t ✅
3. Nincs szükség manuális refresh-re

### Eset 2: Manuális Refresh még mindig elérhető
- Jobb kattintás → "🔄 Regenerate Thumbnail"
- Továbbra is működik, ha szükséges

## Performance Hatások

### ✅ Optimális
- **Memory cache check elsősorban** (gyors, lemez I/O nélkül)
- `needs_refresh()` csak akkor hívódik, ha memory cache miss
- Csak a **látható itemek** kezelnek automatikus refresh-t
- Háttérben nem futnak felesleges frissítések

### Konfigurálás

A `config.json`-ben:
```json
"preload_all_thumbnails": false  // False = csak látható itemek
```

Ha `true` → háttérben is frissít, de több CPU igény.

## Tesztlépések

1. **Nyisd meg a browser-t** egy képmappára
2. **Várakoztass** amíg megjelennek a thumbnail-ek
3. **Módosíts egy képet** (pl. GIMP-ben szerkeszd és mentsd)
4. **Görgess** az item fölé vagy aktiváld az ablakot
5. **Az thumbnail automatikusan frissül** ✅

## Megjegyzések

- Az `asset.modified_time` az `os.stat().st_mtime` alapján számít
- A cache kulcs ez a timestamp-et hash-eli az idempotencia miatt
- Ha a timestamp azonos → cache valid
- Ha a timestamp különbözik → automatikus refresh

## Jövőbeli Fejlesztések

Lehetséges továbbfejlesztések:
- ⚙️ "Auto refresh" toggle beállításban
- 📁 Mappa figyelés (file system watcher) teljes automatizmushoz
- ⏱️ Refresh timeout beállítása
