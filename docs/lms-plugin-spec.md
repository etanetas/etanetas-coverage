# LMS Plus plugin — specyfikacja implementacji

## STATUS: backend gotowy, implementuj frontend

**Krok 1 (Python backend) — ZROBIONE.** Wszystkie potrzebne endpointy istnieją.
Możesz zacząć od razu od frontendu (Krok 2–6 poniżej).

### Gotowe endpointy backendu

Backend działa na `http://localhost:8000`. Auth: header `X-API-Key: etn_pk_...`

```bash
# Strefy z poligonami GeoJSON (dla mapy)
GET  /api/v1/admin/zones                          # lista, polygon_geojson uproszczony
GET  /api/v1/admin/zones/{id}/detail              # szczegóły: polygon + offerings + address_count
POST /api/v1/admin/zones                          # utwórz (body: {name, priority, polygon_geojson})
PUT  /api/v1/admin/zones/{id}                     # edytuj (body: {name?, priority?, polygon_geojson?})
DEL  /api/v1/admin/zones/{id}                     # usuń

# Offerings w strefie
GET  /api/v1/admin/zones/{id}/offerings           # lista
POST /api/v1/admin/zones/{id}/offerings           # dodaj
PUT  /api/v1/admin/zones/offerings/{id}           # edytuj
DEL  /api/v1/admin/zones/offerings/{id}           # usuń

# Mapa — punkty adresów i GeoJSON stref
GET  /api/v1/admin/map/addresses?bbox=lon1,lat1,lon2,lat2   # GeoJSON FeatureCollection, limit=3000
GET  /api/v1/admin/map/zones/geojson              # GeoJSON z offerings summary dla kolorowania

# Adresy i ich offerings
POST /api/v1/admin/addresses/search               # body: {q, locality_code?, rc_codes?, limit?}
GET  /api/v1/admin/addresses/{rc_code}            # szczegóły adresu z lon/lat
GET  /api/v1/admin/addresses/{rc_code}/offerings  # offerings tego adresu
POST /api/v1/admin/addresses/{rc_code}/offerings  # dodaj override
PUT  /api/v1/admin/addresses/offerings/{id}       # edytuj override
DEL  /api/v1/admin/addresses/offerings/{id}       # usuń override

# Bulk operacje
POST /api/v1/admin/bulk/preview                   # body: {operation, filter: {rc_codes: [...]}}
POST /api/v1/admin/bulk/execute                   # body: {preview_token}
POST /api/v1/admin/bulk/{id}/rollback
GET  /api/v1/admin/bulk-operations

# Technologie (dla dropdownów)
GET  /api/v1/admin/technologies                   # lista wariantów (id, display_name, active)
GET  /api/v1/admin/technology-types               # lista typów

# Użytkownicy (LMS integration)
GET  /api/v1/admin/users/by-lms-username/{login}  # szukaj po LMS loginie
GET  /api/v1/admin/me                             # aktualny user
PUT  /api/v1/admin/users/{id}                     # body: {lms_username?, role?, email?, active?}

# Audit
GET  /api/v1/admin/audit-log?entity_type=...&since=...
GET  /api/v1/admin/addresses/{rc_code}/history
```

### Przykładowe odpowiedzi API

**GET /api/v1/admin/zones** (lista z poligonami):
```json
[{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "Šalčininkai centrum",
  "priority": 100,
  "has_polygon": true,
  "polygon_geojson": {"type":"MultiPolygon","coordinates":[[[[25.38,54.30],[25.40,54.30],[25.40,54.32],[25.38,54.32],[25.38,54.30]]]]},
  "created_at": "2026-01-15T10:00:00"
}]
```

**GET /api/v1/admin/zones/{id}/detail**:
```json
{
  "id": "550e8400-...",
  "name": "Šalčininkai centrum",
  "priority": 100,
  "has_polygon": true,
  "polygon_geojson": {"type":"MultiPolygon","coordinates":[...]},
  "created_at": "2026-01-15T10:00:00",
  "address_count": 234,
  "offerings": [{
    "id": "...", "zone_id": "...",
    "technology_id": "...",
    "status": "available",
    "max_download_mbps": 1000,
    "max_upload_mbps": 500,
    "status_since": "2024-03-15",
    "planned_until": null
  }]
}
```

**GET /api/v1/admin/map/addresses?bbox=25.35,54.28,25.45,54.35**:
```json
{
  "type": "FeatureCollection",
  "features": [{
    "type": "Feature",
    "geometry": {"type":"Point","coordinates":[25.39,54.31]},
    "properties": {
      "rc_code": 1234567,
      "label": "Vilniaus g. 12",
      "has_address_offering": false
    }
  }]
}
```

**GET /api/v1/admin/map/zones/geojson**:
```json
{
  "type": "FeatureCollection",
  "features": [{
    "type": "Feature",
    "geometry": {"type":"MultiPolygon","coordinates":[...]},
    "properties": {
      "id": "...", "name": "Šalčininkai centrum", "priority": 100,
      "offerings": [{
        "status": "available",
        "technology_type": "FIBER",
        "public_name": "Šviesolaidis",
        "max_download_mbps": 1000,
        "planned_until": null
      }]
    }
  }]
}
```

**POST /api/v1/admin/zones** (utwórz strefę z poligonem):
```json
// Request body:
{
  "name": "Eišiškių g. 2024",
  "priority": 200,
  "polygon_geojson": {
    "type": "MultiPolygon",
    "coordinates": [[[[25.39, 54.31], [25.40, 54.31], [25.40, 54.32], [25.39, 54.32], [25.39, 54.31]]]]
  }
}
// Potem osobno dodaj offering:
// POST /api/v1/admin/zones/{id}/offerings
// {"technology_id":"...", "status":"available", "max_download_mbps":1000, "max_upload_mbps":500, "status_since":"2026-05-20"}
```

---

## Kontekst

Backend Etanetas (FastAPI + PostgreSQL/PostGIS) jest gotowy — etapy 1–4 zrobione.
Etap 5 to **LMS Plus plugin**: interfejs admin dla pracowników ISP, osadzony w istniejącym
systemie LMS PHP, który pracownicy otwierają codziennie.

Pracownicy nie potrzebują nowego logowania ani nowej aplikacji. Plugin to zakładka w LMS.

---

## Fundament UX: mapa jest głównym interfejsem

Pokrycie sieciowe to problem przestrzenny. Tabelki z adresami są wtórne.

**Główny workflow admina:**

```
Technik kładzie kabel → Admin otwiera mapę → Rysuje strefę → Done
```

Zamiast:
```
Admin szuka 50 adresów → zaznacza → bulk execute → (jutro nowy adres = nie ma pokrycia)
```

Strefy są wieczne. Nowy adres z ETL automatycznie dostaje pokrycie przez `ST_Contains`.
Bulk operations to edge cases, nie główny workflow.

---

## Jak działa pokrycie (priorytet)

```
address_offerings (konkretny adres)  ← ZAWSZE wygrywa
        ↑ jeśli nie ma ↑
zone_offerings (strefa) + ST_Contains  ← priorytet strefy decyduje przy nakładaniu
```

**Przykład:**
- Strefa "Eišiškės centrum" (priorytet 100): GPON planned, until 2026-09
- Strefa "Eišiškių g. 1–20" (priorytet 200): GPON available — nakrywa podzbiór adresów
- Adres Eišiškių g. 12: dostaje GPON available (wyższy priorytet)
- Adres Eišiškių g. 99: dostaje GPON planned (tylko niższy priorytet)
- Adres z ręcznym `address_offering`: dostaje to co w address_offering, niezależnie od stref

---

## Architektura

```
┌─────────────────────────────────────────────────────────────────┐
│  PRZEGLĄDARKA                                                   │
│  Smarty template + Leaflet.js + Alpine.js + HTMX               │
│  JS wywołuje Python API bezpośrednio (X-API-Key z PHP → JS)    │
└──────────────────┬──────────────────────────────────────────────┘
                   │ PHP Guzzle (server-side, tylko POST z CSRF)
┌──────────────────▼──────────────────────────────────────────────┐
│  LMS PLUGIN PHP                                                  │
│  Rejestracja hooków, sesja LMS → API key, Smarty render        │
└──────────────────┬──────────────────────────────────────────────┘
                   │ HTTPS + X-API-Key
┌──────────────────▼──────────────────────────────────────────────┐
│  PYTHON BACKEND (etanetas-coverage)                             │
│  Cała logika. Plugin jest tylko cienkim klientem.               │
└─────────────────────────────────────────────────────────────────┘
```

**Kluczowa zasada:** JS w przeglądarce wywołuje Python API bezpośrednio (Leaflet,
Alpine fetch). PHP tylko renderuje stronę i wstrzykuje API key.

---

## Najpierw: zmiany w Python backend

Zanim zaczniesz PHP/frontend, dołóż do backendu:

### 1. Endpoint strefy z GeoJSON polygonu

Aktualnie `GET /api/v1/admin/zones` zwraca tylko `has_polygon: bool`.
Mapa potrzebuje rzeczywistego GeoJSON.

**Dodaj:** `GET /api/v1/admin/zones/{id}` zwracający ZoneDetail z poligonem:

```python
class ZoneDetail(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    priority: int
    created_at: datetime
    polygon_geojson: dict | None  # ST_AsGeoJSON(ST_SimplifyPreserveTopology(polygon, 0.0001))
    offerings: list[ZoneOfferingOut]
    address_count: int  # COUNT adresów w poligonie (z cache lub live query)
```

SQL dla polygonu (zoptymalizowany pod mapę):
```sql
SELECT ST_AsGeoJSON(ST_SimplifyPreserveTopology(polygon, 0.0001))::jsonb
FROM service_zones WHERE id = :id
```

`ST_SimplifyPreserveTopology(0.0001)` — upraszcza polygon bez zrywania topologii,
zmniejsza rozmiar odpowiedzi ~10×. Wystarczy dla wizualizacji.

Dla `address_count`:
```sql
SELECT COUNT(*) FROM addresses a
WHERE ST_Contains(
  (SELECT polygon FROM service_zones WHERE id = :zone_id),
  a.point
) AND a.deleted_at IS NULL
```

To jest drogie — cachuj po zapisie strefy lub uruchamiaj async.

**Zaktualizuj też `GET /api/v1/admin/zones`** aby zwracał uproszczony GeoJSON
(niezbędny do narysowania wszystkich stref przy załadowaniu mapy):

```python
class ZoneListItem(BaseModel):
    id: uuid.UUID
    name: str
    priority: int
    has_polygon: bool
    polygon_geojson: dict | None  # ST_AsGeoJSON(ST_Simplify(polygon, 0.001)) — bardziej agresywne
    offerings_summary: list[dict]  # [{status, technology_public_name, color_hint}]
```

### 2. Endpoint punktów adresowych dla mapy (bbox)

```python
GET /api/v1/admin/map/addresses?bbox=lon1,lat1,lon2,lat2&limit=3000

# Odpowiedź: GeoJSON FeatureCollection
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": {"type": "Point", "coordinates": [25.39, 54.31]},
      "properties": {
        "rc_code": 1234567,
        "label": "Vilniaus g. 12",
        "has_address_offering": false  # czy ma indywidualne offerings (override)
      }
    }
  ]
}
```

Ważne: tylko budynki (`address_type = 'building'`), tylko z `point IS NOT NULL`.
Limit 3000 — przy zoom < 14 zwróć pusty wynik lub tylko centroidy gmin.

Zoptymalizuj przez GIST index (już istnieje: `idx_addresses_street`).

### 3. Pole `lms_username` w User

Mapowanie LMS login → nasz user:

```python
# W modelu User — dodaj pole
lms_username: Mapped[str | None] = mapped_column(Text, unique=True, nullable=True)

# W UserUpdate — pozwól na ustawienie
lms_username: str | None = None

# Nowy endpoint do wyszukiwania po lms_username (dla PHP)
GET /api/v1/admin/users/by-lms-username/{lms_username}
```

Potrzebna migracja Alembic: `ADD COLUMN lms_username TEXT UNIQUE`.

### 4. Endpoint statusów pokrycia strefy (opcjonalny ale przydatny)

```python
GET /api/v1/admin/zones/{id}/addresses?bbox=...&limit=500

# Zwraca adresy WEWNĄTRZ tej strefy z ich efektywnym pokryciem
# Używane do: "pokaż mi co ta strefa faktycznie pokrywa"
```

---

## Struktura PHP pluginu

```
lms-plugin-addresses/
│
├── plugin.php              # Rejestracja hooków LMS — główny punkt wejścia
├── menu.xml                # Definicja zakładek w menu LMS
├── README.md
│
├── lib/
│   ├── ApiClient.php       # Guzzle wrapper — wszystkie wywołania Python API
│   ├── SessionAuth.php     # LMS sesja → API key mapping
│   └── Controllers/
│       ├── MapController.php         # GET /lms-addresses/map
│       ├── ZoneController.php        # GET/POST /lms-addresses/zones
│       ├── AddressController.php     # GET /lms-addresses/addresses
│       ├── TechnologyController.php  # GET/POST /lms-addresses/technologies
│       ├── UserController.php        # GET/POST /lms-addresses/users
│       └── AuditController.php       # GET /lms-addresses/audit
│
├── templates/
│   ├── map.tpl             # GŁÓWNY EKRAN — mapa Leaflet
│   ├── zones.tpl           # Lista stref (HTMX)
│   ├── addresses.tpl       # Tabela adresów (Alpine)
│   ├── technologies.tpl    # Katalog technologii (HTMX)
│   ├── users.tpl           # Użytkownicy (HTMX)
│   ├── audit.tpl           # Historia zmian (HTMX)
│   └── partials/
│       ├── zone_panel.tpl          # Sidebar strefy (HTMX fragment)
│       ├── address_popup.tpl       # Popup adresu (HTMX fragment)
│       ├── zone_offering_form.tpl  # Formularz offering (HTMX fragment)
│       └── bulk_preview.tpl        # Modal potwierdzenia bulk (Alpine)
│
├── assets/
│   ├── js/
│   │   ├── leaflet.min.js       # Leaflet 1.9.x
│   │   ├── leaflet.draw.min.js  # Leaflet.draw 1.0.x
│   │   ├── alpine.min.js        # Alpine.js 3.x
│   │   ├── htmx.min.js          # HTMX 2.x
│   │   └── app.js               # Komponenty Alpine: mapManager(), addressManager()
│   └── css/
│       ├── leaflet.min.css
│       ├── leaflet.draw.min.css
│       └── plugin.css           # Style dopasowane do LMS
│
└── db/
    └── install.sql              # Tabela mapowania LMS username (jeśli nie w Python DB)
```

---

## Autentykacja: LMS sesja → X-API-Key

### Setup (jednorazowy, admin)

1. Utwórz pracownika w Python API:
   ```bash
   uv run python -m app.cli create-admin --username jonas --email j@etanetas.lt
   # → API key: etn_pk_...
   ```

2. W LMS plugin → Użytkownicy → "Susieti su LMS":
   - Nasz użytkownik: `jonas`
   - LMS login: `jonas.kazlauskas`
   - Kliknij Zapisz → PHP wywołuje `PUT /api/v1/admin/users/jonas_uuid` ustawiając `lms_username = "jonas.kazlauskas"`

### Przy każdym otwarciu pluginu

```php
// SessionAuth.php
class SessionAuth {
    public function getApiKeyForCurrentUser(): string {
        $lmsUser = $this->LMS->getUserInfo();
        $lmsLogin = $lmsUser['login'];

        // Wywołaj Python API — szukaj usera po lms_username
        $user = $this->apiClient->getWithoutAuth(
            "/api/v1/admin/users/by-lms-username/{$lmsLogin}"
        );

        // Pobierz aktywny klucz z cache (session) lub fresh
        return $this->getActiveApiKey($user['id']);
    }
}
```

**Bezpieczeństwo:** Raw API key nigdy nie trafia do DB. PHP przechowuje go w PHP sesji
(zaszyfrowanej), nie w cookie przeglądarki. JS dostaje klucz przez wstrzyknięcie
`window.apiKey` przy renderze strony — tylko na czas sesji.

```php
// map.tpl — PHP renderuje to przed wysłaniem do przeglądarki
<script>
window.apiKey = "<?= htmlspecialchars($apiKey, ENT_QUOTES) ?>";
window.apiBaseUrl = "<?= API_BASE_URL ?>";
</script>
```

---

## Ekran 1: Mapa pokrycia (GŁÓWNY)

### Widok ogólny

```
┌─────────────────────────────────────────────────────────────────┐
│ 🗺️  Pokrycie sieci        [+ Nowa strefa]  [Warstwy ▾]  [🔍]  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌───────────────────────────────────────────────┐  ┌────────┐ │
│  │                                               │  │ SIDEBAR│ │
│  │   [MAPA — OpenStreetMap tiles]                │  │ (empty │ │
│  │                                               │  │  stan) │ │
│  │  🟢 Strefa GPON available                    │  │        │ │
│  │  🟡 Strefa GPON planned                      │  │        │ │
│  │  🟠 Strefa Wireless available                │  │        │ │
│  │  🔵 Punkty adresów (zoom ≥ 15)              │  │        │ │
│  │                                               │  │        │ │
│  │  [toolbar rysowania: ✏️ 📐 ✂️]              │  │        │ │
│  │                                               │  │        │ │
│  └───────────────────────────────────────────────┘  └────────┘ │
│                                                                 │
│  Legenda: ■ GPON avail  ░ GPON plan  ▪ Wireless  ▫ LTE        │
└─────────────────────────────────────────────────────────────────┘
```

### Kolory stref

| Technologia | Available | Planned | Under construction |
|---|---|---|---|
| GPON/xGPON (Fiber) | zielony `#22c55e` | zielony przerywany `#86efac` | zielony kreskowany |
| Wireless | pomarańczowy `#f97316` | pomarańczowy przerywany | |
| LTE | fioletowy `#a855f7` | fioletowy przerywany | |
| Ethernet | niebieski `#3b82f6` | niebieski przerywany | |

Przerywana linia (`dashArray: '8, 4'`) = planned. Kreskowane fill = under_construction.

Wiele offerings w jednej strefie → kolor najwyższego statusu (available > planned > construction).

### Interakcje na mapie

**Kliknięcie na strefę:**
```
Sidebar otwiera się:
┌──────────────────────────────┐
│ Eišiškės centrum             │
│ Priorytet: 100               │
│ Adresų: 234                  │
│                              │
│ Paslaugos:                   │
│ ●🟢 GPON · available         │
│    1000↓ / 500↑ Mbps         │
│    od 2024-03-15             │
│ ●🟡 Wireless · planned       │
│    100↓ / 50↑                │
│    do 2026-09-01             │
│                              │
│ [Redaguoti strefą]           │
│ [+ Pridėti paslaugą]         │
│ [🗑️ Ištrinti strefą]          │
└──────────────────────────────┘
```

**Kliknięcie na adres (punkt, zoom ≥ 15):**
```
Popup:
┌────────────────────────────────┐
│ Vilniaus g. 12, Šalčininkai   │
│ RC: 1234567  • budynek        │
│                                │
│ Pokrycie:                      │
│ ✓ GPON available — strefa     │
│   "Eišiškės centrum"          │
│   1000↓ / 500↑ Mbps          │
│                                │
│ [+ Pridėti išimtį (override)] │
│ [📋 Historia]                  │
└────────────────────────────────┘
```

**Brak pokrycia (kliknięcie na adres bez strefy):**
```
Popup:
┌─────────────────────────────┐
│ Medžių g. 5, Butrimonys     │
│                             │
│ ❌ Brak pokrycia            │
│                             │
│ [+ Pridėti į naują strefą] │
│ [+ Priskirti atskirai]     │
└─────────────────────────────┘
```

**Nakładające się strefy (kliknięcie na adres w overlap):**
```
Popup:
┌─────────────────────────────────┐
│ Eišiškių g. 12, Eišiškės       │
│                                 │
│ Efektyvus pokrycie:             │
│ ✓ GPON available               │
│   (strefa "Eišiškių g." pr.200)│
│                                 │
│ Strefy nakładające się:         │
│ • Eišiškių g. (pr.200) ← wygr. │
│ • Eišiškės centrum (pr.100)    │
└─────────────────────────────────┘
```

### Rysowanie nowej strefy

1. Kliknij `[+ Nowa strefa]` — mapa wchodzi w tryb rysowania
2. Leaflet.draw toolbar: narysuj polygon klikając punkty → double-click zamyka
3. Podczas rysowania: punkty adresów wewnątrz podświetlają się na niebiesko (live preview)
4. Po zamknięciu → sidebar otwiera formularz:

```
┌──────────────────────────────────┐
│ Nowa strefa                      │
│                                  │
│ Nazwa: [_____________________]   │
│ Priorytet: [100]                 │
│ Opis: [________________________] │
│                                  │
│ Pokryte adresy: 47               │
│                                  │
│ Paslaugos (dodaj offering):      │
│ Technologia: [GPON ▾]           │
│ Status:      [available ▾]       │
│ ↓ Mbit/s:   [1000]              │
│ ↑ Mbit/s:   [500 ]              │
│ Data od:    [2026-05-20]         │
│ Planuojama iki: [          ]     │
│                                  │
│ [+ Pridėti dar vieną technologiją]│
│                                  │
│ [Atšaukti]  [Išsaugoti strefą]  │
└──────────────────────────────────┘
```

Po zapisaniu: polygon pojawia się na mapie z właściwym kolorem.

### Edycja istniejącej strefy

Kliknij na strefę → sidebar → `[Redaguoti]`:
- Leaflet.draw tryb edycji — można przeciągać wierzchołki poligonu
- Sidebar zmienia się na formularz edycji
- `[Išsaugoti]` → `PUT /api/v1/admin/zones/{id}` z nowym GeoJSON

### Warstwy (Layer control)

```
Warstwy:
☑ Strefy pokrycia
☑ Adresy (zoom ≥ 15)
☐ Adresy bez pokrycia (highlights)
☐ Nakładające się strefy
─────────────────────
Technologie:
☑ GPON/Fiber
☑ Wireless
☑ LTE
☑ Ethernet
```

---

## Ekran 2: Tabela adresów (Alpine)

Ekran wtórny — dla bulk operations i szczegółowego wyszukiwania.

```
┌───────────────────────────────────────────────────────────────┐
│ Adresy   [Szukaj...🔍]  [Savivaldybė▾] [Gyvenv.▾] [Gatvė▾]  │
│          [Technologia▾] [Statusas▾]    [Tik be pokrycia □]   │
├───────────────────────────────────────────────────────────────┤
│ ☐ Adresas            Paštas  Technologijos          Veiksmai  │
├───────────────────────────────────────────────────────────────┤
│ ☑ Vilniaus g. 12     01234   🟢GPON 🟡Wireless               │
│ ☑ Vilniaus g. 14     01234   🟢GPON                          │
│ ☐ Medžių g. 5        01235   —  (brak pokrycia)              │
│   ▸ rozwiń → pełna lista offerings                           │
├───────────────────────────────────────────────────────────────┤
│ Zaznaczono: 2 z 47   [Grupinė operacija ▾]  [Wyczyść]        │
└───────────────────────────────────────────────────────────────┘
```

**Bulk operations flow (z tabeli):**

1. Zaznacz adresy
2. Wybierz operację z dropdown:
   - Pridėti technologiją (add offering)
   - Keisti statusą (change status)
   - Keisti planuojamą datą
   - Pašalinti technologiją (remove offering)
3. Kliknij → modal preview
4. Zatwierdź → execute → toast z [Anuliuoti 15min]

Filtr "Tik be pokrycia" — pokazuje tylko adresy bez żadnego offerings. Przydatne do
znajdowania białych plam.

---

## Ekran 3: Strefy (lista, backup view)

Lista dla administratorów preferujących tabelki zamiast mapy.

```
Strefy pokrycia
[+ Nowa strefa]

Pavadinimas              Prior  Adresai  Paslaugos          Veiksmai
─────────────────────────────────────────────────────────────────────
Eišiškės centrum         100    234      🟢GPON 🟠Wireless   [✏️][🗺️][🗑️]
Eišiškių g. 1-50         200     47      🟢GPON              [✏️][🗺️][🗑️]
Šalčininkai centrum      150    892      🟢GPON 🟢xGPON      [✏️][🗺️][🗑️]
```

`[🗺️]` — kliknięcie otwiera mapę wycentrowaną na tej strefie.

HTMX: edycja inline (kliknięcie [✏️] → wiersz zamienia się w formularz).

---

## Ekran 4–6: Technologie, Użytkownicy, Audit (proste)

Standardowe HTMX CRUD — bez map, bez skomplikowanego stanu.

**Technologie:** lista typów (GPON, LTE...) i wariantów. Admin może zmienić
`display_name`, `sort_order`, `active`. Brak usuwania (soft only).

**Użytkownicy:** lista + tworzenie + mapowanie LMS username. Każdy user ma
klucze API (lista + revoke + generate).

**Audit log:** filtrowane po typie encji, dacie, userze. HTMX paginacja.
Link "Historia" z popupu adresu otwiera audit przefiltrowany do tego adresu.

---

## Szczegóły implementacji: Alpine komponent mapy

```javascript
// assets/js/app.js

function mapManager() {
  return {
    map: null,
    zonesLayer: null,
    addressesLayer: null,
    drawControl: null,
    selectedZone: null,
    selectedAddress: null,
    isDrawing: false,
    newZoneGeoJSON: null,
    zoneForm: { name: '', priority: 100, offerings: [] },

    async init() {
      this.map = L.map('map').setView([54.31, 25.39], 11);
      L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OSM | RC adresai'
      }).addTo(this.map);

      this.zonesLayer = L.featureGroup().addTo(this.map);
      this.addressesLayer = L.featureGroup().addTo(this.map);

      // Leaflet.draw
      this.drawControl = new L.Control.Draw({
        draw: { polygon: { shapeOptions: { color: '#3b82f6' }}, circle: false, marker: false, polyline: false, rectangle: false },
        edit: { featureGroup: this.zonesLayer }
      });

      this.map.on('draw:created', e => this.onPolygonDrawn(e));
      this.map.on('draw:edited', e => this.onPolygonEdited(e));
      this.map.on('moveend', () => this.loadAddresses());
      this.map.on('zoomend', () => this.loadAddresses());

      await this.loadZones();
    },

    async loadZones() {
      const resp = await fetch(`${window.apiBaseUrl}/api/v1/admin/zones`, {
        headers: { 'X-API-Key': window.apiKey }
      });
      const zones = await resp.json();
      this.zonesLayer.clearLayers();

      zones.forEach(zone => {
        if (!zone.polygon_geojson) return;
        const color = this.zoneColor(zone);
        const layer = L.geoJSON(zone.polygon_geojson, {
          style: { color, weight: 2, fillOpacity: 0.25, dashArray: zone.is_planned ? '8,4' : null },
          onEachFeature: (feature, layer) => {
            layer.on('click', () => this.selectZone(zone.id));
          }
        });
        this.zonesLayer.addLayer(layer);
      });
    },

    async loadAddresses() {
      if (this.map.getZoom() < 15) {
        this.addressesLayer.clearLayers();
        return;
      }
      const b = this.map.getBounds();
      const bbox = `${b.getWest()},${b.getSouth()},${b.getEast()},${b.getNorth()}`;
      const resp = await fetch(
        `${window.apiBaseUrl}/api/v1/admin/map/addresses?bbox=${bbox}`,
        { headers: { 'X-API-Key': window.apiKey } }
      );
      const geojson = await resp.json();
      this.addressesLayer.clearLayers();
      L.geoJSON(geojson, {
        pointToLayer: (f, latlng) => L.circleMarker(latlng, {
          radius: 4,
          color: f.properties.has_address_offering ? '#f97316' : '#3b82f6',
          weight: 1, fillOpacity: 0.7
        }),
        onEachFeature: (f, layer) => {
          layer.on('click', () => this.selectAddress(f.properties.rc_code));
        }
      }).addTo(this.addressesLayer);
    },

    startDrawing() {
      this.isDrawing = true;
      new L.Draw.Polygon(this.map).enable();
    },

    onPolygonDrawn(e) {
      this.isDrawing = false;
      this.newZoneGeoJSON = e.layer.toGeoJSON().geometry;
      // Konwersja Polygon → MultiPolygon dla DB
      if (this.newZoneGeoJSON.type === 'Polygon') {
        this.newZoneGeoJSON = { type: 'MultiPolygon', coordinates: [this.newZoneGeoJSON.coordinates] };
      }
      this.selectedZone = null;
      this.selectedAddress = null;
      this.$dispatch('zone-draw-complete', { geojson: this.newZoneGeoJSON });
    },

    async selectZone(zoneId) {
      const resp = await fetch(`${window.apiBaseUrl}/api/v1/admin/zones/${zoneId}`, {
        headers: { 'X-API-Key': window.apiKey }
      });
      this.selectedZone = await resp.json();
    },

    async selectAddress(rcCode) {
      // Pobierz offerings (effective + source)
      const resp = await fetch(`${window.apiBaseUrl}/api/v1/admin/addresses/${rcCode}/offerings`, {
        headers: { 'X-API-Key': window.apiKey }
      });
      const offerings = await resp.json();
      this.selectedAddress = { rcCode, offerings };
    },

    zoneColor(zone) {
      // Zwraca kolor na podstawie dominującego offering
      const colors = { fiber: '#22c55e', wireless: '#f97316', lte: '#a855f7', ethernet: '#3b82f6' };
      // ... logika na podstawie offerings_summary
      return '#22c55e'; // default
    },

    async saveNewZone() {
      await fetch(`${window.apiBaseUrl}/api/v1/admin/zones`, {
        method: 'POST',
        headers: { 'X-API-Key': window.apiKey, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: this.zoneForm.name,
          priority: this.zoneForm.priority,
          polygon_geojson: this.newZoneGeoJSON
        })
      });
      await this.loadZones();
      this.newZoneGeoJSON = null;
      this.zoneForm = { name: '', priority: 100, offerings: [] };
    }
  }
}
```

---

## Kolejność implementacji (ważne)

### Krok 1 — Python backend (2–3 dni)
1. Dodaj `lms_username` do User model + migracja
2. Endpoint `GET /api/v1/admin/users/by-lms-username/{username}`
3. Endpoint `GET /api/v1/admin/zones/{id}` z polygon GeoJSON + offerings + address_count
4. Zaktualizuj `GET /api/v1/admin/zones` aby zwracał uproszczony polygon GeoJSON
5. Endpoint `GET /api/v1/admin/map/addresses?bbox=...`

### Krok 2 — PHP struktura (1 dzień)
1. `plugin.php` — rejestracja hooków LMS
2. `ApiClient.php` — Guzzle wrapper
3. `SessionAuth.php` — LMS sesja → API key
4. Podstawowy routing (MapController, ZoneController)

### Krok 3 — Mapa (3–4 dni)
1. `map.tpl` z Leaflet + Alpine szkielet
2. Załadowanie i wyświetlenie stref (polygon GeoJSON → kolorowe warstwy)
3. Załadowanie adresów przy zoom ≥ 15
4. Kliknięcie na strefę → sidebar z detalami (HTMX fragment)
5. Kliknięcie na adres → popup z pokryciem
6. Rysowanie nowej strefy + formularz + zapis

### Krok 4 — Edycja stref
1. Edycja polygon (Leaflet.draw edit mode)
2. Edycja offerings (zmiana statusu, dat, prędkości)
3. Usuwanie strefy z potwierdzeniem

### Krok 5 — Tabela adresów (2 dni)
1. Ekran `addresses.tpl` z Alpine
2. Wyszukiwanie + filtry
3. Bulk operations (korzysta z gotowego Python API)

### Krok 6 — Pozostałe ekrany (2 dni)
1. `technologies.tpl` — prosty HTMX CRUD
2. `users.tpl` — zarządzanie userami + mapowanie LMS
3. `audit.tpl` — historia zmian

---

## Kluczowe decyzje projektowe do podjęcia

**1. Gdzie przechowywać raw API key w PHP sesji?**
Opcja A: PHP `$_SESSION['etanetas_api_key']` — prosto, ale ryzyko jeśli sesja wycieknie
Opcja B: Szyfruj kluczem derivowanym z hasła LMS — bardziej bezpieczne
Rekomendacja: Opcja A + HTTPS + short session TTL (LMS i tak zarządza sesją)

**2. Jak obsługiwać wiele offerings w jednej strefie na mapie?**
Opcja A: Jeden kolor na technologię z najwyższym statusem
Opcja B: Pasek kolorów na granicy strefy (każda technologia = osobny kolor krawędzi)
Opcja C: Oddzielne warstwy per technologia (toggle w Layer control)
Rekomendacja: Opcja A + Opcja C (warstwy do toggle)

**3. MULTIPOLYGON vs POLYGON — czy admin może rysować wiele wysp?**
TZ specyfikuje MULTIPOLYGON w DB. Leaflet.draw rysuje pojedynczy Polygon.
Rekomendacja MVP: jeden polygon na strefę (konwertuj Polygon → MultiPolygon[1]).
Jeśli potrzeba wysp (np. dwa odcinki tej samej ulicy) — dodaj możliwość
"Pridėti kitą dalį" który dodaje drugi polygon do tej samej strefy.

**4. address_count — live query czy cache?**
Live query przy każdym załadowaniu mapy = drogie (ST_Contains na 2.3M adresów).
Rekomendacja: Cache po stronie Python (przy CREATE/UPDATE strefy uruchamiaj
async task który liczy i zapisuje do `service_zones.address_count` — nowe pole).
Albo: licz tylko kiedy sidebar strefy jest otwarty (lazy load).

---

## Co NIE jest w pluginie (delegowane do CLI lub bezpośrednio API)

- Tworzenie pierwszego admina → `uv run python -m app.cli create-admin`
- Rotacja kluczy → `uv run python -m app.cli revoke-key` + `create-key`
- ETL import → `uv run python -m etl.tasks.full_import`
- Backup bazy → systemowe narzędzia DB

---

## Testy E2E (smoke test po wdrożeniu)

```bash
# 1. LMS login Jonas → plugin widoczny w menu
# 2. Otwórz mapę → widać istniejące strefy w kolorach
# 3. Zoom in → adresy jako punkty
# 4. Kliknij strefę → sidebar z offerings
# 5. Kliknij adres → popup z pokryciem
# 6. Narysuj nową strefę → zapisz → pojawia się na mapie
# 7. Kliknij adres wewnątrz → popup pokazuje nową strefę
# 8. Otwórz zakładkę Adresy → wyszukaj ulicę → zaznacz 5 → bulk → preview → execute
# 9. Toast "Pakeista 5 adresai" → [Anuliuoti] → rollback działa
# 10. Audit log → widać wszystkie zmiany
```

---

## Zewnętrzne zależności (do sprawdzenia przed startem)

- **LMS Plus** — wersja i dokumentacja hooków. Plugin musi być testowany na
  tej samej wersji co produkcja.
- **Guzzle** — `composer require guzzlehttp/guzzle:^7.0`
- **Leaflet.js 1.9.x** + **Leaflet.draw 1.0.x** — pobrać lokalnie (nie CDN)
- **Alpine.js 3.14.x** + **HTMX 2.x** — pobrać lokalnie
- **CORS** — Python backend musi dopuścić origin LMS serwera.
  Dodać do `CORS_ORIGINS` w `.env` adres serwera LMS.
- **PostgreSQL** — dostęp z serwera LMS (jeśli PHP tworzy bezpośrednie połączenie DB)
  lub tylko HTTPS do Python API (rekomendowane).
