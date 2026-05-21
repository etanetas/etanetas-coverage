# Prompt dla AI: LMS Plus plugin — Etanetas adresų sistema

## Co budujesz

Plugin do systemu **LMS Plus** (PHP ISP management system) dla firmy Etanetas
(Šalčininkai, LT). Plugin dodaje zakładkę "Adresų sistema" do LMS, przez którą
pracownicy ISP zarządzają pokryciem sieci — które adresy mają dostęp do
internetu, jakimi technologiami i z jakimi prędkościami.

**Gotowy Python backend** wystawia REST API na `http://localhost:8000` (lub produkcja).
Twoja robota to PHP plugin + HTML/JS frontend. Cała logika biznesowa jest w backendzie.

---

## Stos technologiczny

| Co | Technologia | Dlaczego |
|---|---|---|
| Plugin server-side | PHP (LMS hooks + Guzzle) | LMS jest w PHP |
| Szablony | Smarty (LMS native) | Integracja wizualna z LMS |
| Mapa | Leaflet.js 1.9 + Leaflet.draw 1.0 | Rysowanie stref pokrycia |
| Interaktywność (złożona) | Alpine.js 3.14 | Reaktywny state bez buildu |
| Interaktywność (prosta) | HTMX 2.x | AJAX z serwera bez JS |
| HTTP klient | guzzlehttp/guzzle ^7 | PHP → Python API |

**Brak buildowania.** Alpine/HTMX/Leaflet jako lokalne pliki JS. Brak npm/webpack.

---

## Struktura projektu do stworzenia

```
lms-plugin-etanetas/
├── plugin.php                    # Rejestracja hooków LMS (entry point)
├── menu.xml                      # Definicja zakładek w menu LMS
├── composer.json                 # Zależność: guzzlehttp/guzzle
├── lib/
│   ├── EtaApiClient.php          # Guzzle wrapper na Python API
│   ├── EtaSessionAuth.php        # LMS sesja → API key
│   └── Controllers/
│       ├── MapController.php     # Ekran: mapa pokrycia
│       ├── ZoneController.php    # Ekran: lista stref
│       ├── AddressController.php # Ekran: tabela adresów
│       ├── TechController.php    # Ekran: katalog technologii
│       ├── UserController.php    # Ekran: użytkownicy
│       └── AuditController.php   # Ekran: audit log
├── templates/
│   ├── map.tpl           # GŁÓWNY EKRAN z mapą Leaflet + Alpine
│   ├── zones.tpl         # Lista stref (HTMX CRUD)
│   ├── addresses.tpl     # Tabela adresów (Alpine + bulk ops)
│   ├── technologies.tpl  # Katalog (HTMX)
│   ├── users.tpl         # Użytkownicy + mapowanie LMS (HTMX)
│   ├── audit.tpl         # Historia zmian (HTMX)
│   └── partials/
│       ├── zone_sidebar.tpl       # Sidebar szczegółów strefy
│       ├── address_popup.tpl      # Popup adresu na mapie
│       ├── zone_offering_form.tpl # Formularz dodawania usługi do strefy
│       └── bulk_preview.tpl       # Modal potwierdzenia bulk operacji
└── assets/
    ├── js/
    │   ├── leaflet.min.js
    │   ├── leaflet.draw.min.js
    │   ├── alpine.min.js
    │   ├── htmx.min.js
    │   └── eta-map.js        # Główny Alpine komponent mapy
    └── css/
        ├── leaflet.min.css
        ├── leaflet.draw.min.css
        └── eta-plugin.css    # Style integrujące się z LMS
```

---

## Autentykacja (KLUCZOWE)

### Jak to działa

LMS zarządza sesjami pracowników. Plugin tłumaczy LMS sesję na API key dla
Python backendu.

```
Pracownik loguje się do LMS → LMS sesja PHP
Plugin czyta: $LMS->getUserInfo()['login']   → np. "jonas.kazlauskas"
Szuka w Python API: GET /api/v1/admin/users/by-lms-username/jonas.kazlauskas
Dostaje: { id, username, role, ... }
Pobiera aktywny API key tego usera z Python API
Przechowuje raw key w PHP $_SESSION['eta_api_key'] (tylko na czas sesji)
Wstrzykuje do HTML: window.etaApiKey = "etn_pk_..."  ← dla JS/Leaflet
```

### EtaSessionAuth.php (implementuj to)

```php
<?php
class EtaSessionAuth {
    private $LMS;
    private EtaApiClient $client;

    public function __construct($LMS, EtaApiClient $client) {
        $this->LMS = $LMS;
        $this->client = $client;
    }

    public function getApiKey(): ?string {
        // Cache w sesji PHP
        if (!empty($_SESSION['eta_api_key'])) {
            return $_SESSION['eta_api_key'];
        }

        $lmsLogin = $this->LMS->getUserInfo()['login'] ?? null;
        if (!$lmsLogin) return null;

        // Znajdź usera po LMS loginie
        try {
            $user = $this->client->getAnonymous("/api/v1/admin/users/by-lms-username/{$lmsLogin}");
        } catch (Exception $e) {
            return null; // User nie istnieje w systemie Etanetas
        }

        // Pobierz aktywny klucz
        $keys = $this->client->get("/api/v1/admin/users/{$user['id']}/api-keys");
        foreach ($keys as $key) {
            if (empty($key['revoked_at'])) {
                // Nie możemy dostać raw key z API (hash tylko) — klucz musi być w sesji
                // po pierwszym zalogowaniu przez ekran Users
                break;
            }
        }

        return $_SESSION['eta_api_key'] ?? null;
    }

    public function setApiKey(string $rawKey): void {
        $_SESSION['eta_api_key'] = $rawKey;
    }

    public function hasAccess(): bool {
        return !empty($this->getApiKey());
    }
}
```

**UWAGA na chicken-egg problem:** Raw API key jest pokazywany tylko przy tworzeniu.
Rozwiązanie: ekran pierwszego uruchomienia gdzie admin wkleja swój API key.
Potem PHP trzyma go w sesji. Przy następnym logowaniu — z sesji.

### Pierwsze uruchomienie (setup flow)

Jeśli `$_SESSION['eta_api_key']` jest pusty → pokaż formularz setup:

```
┌────────────────────────────────────────────┐
│ Etanetas — pierwsze uruchomienie           │
│                                            │
│ Wklej swój API key:                        │
│ [etn_pk_________________________________]  │
│                                            │
│ (Klucz wygeneruj: uv run python -m         │
│  app.cli create-key --username X)          │
│                                            │
│ [Zaloguj]                                  │
└────────────────────────────────────────────┘
```

Po zalogowaniu PHP sprawdza key przez `GET /api/v1/admin/me`. Jeśli OK —
zapisuje w sesji i kontynuuje.

---

## EtaApiClient.php (implementuj to)

```php
<?php
use GuzzleHttp\Client;

class EtaApiClient {
    private Client $http;
    private string $apiKey;
    private string $baseUrl;

    public function __construct(string $baseUrl, string $apiKey = '') {
        $this->baseUrl = rtrim($baseUrl, '/');
        $this->apiKey = $apiKey;
        $this->http = new Client([
            'base_uri' => $this->baseUrl,
            'timeout' => 15,
            'http_errors' => false,
        ]);
    }

    public function setApiKey(string $key): void {
        $this->apiKey = $key;
    }

    private function headers(): array {
        return [
            'X-API-Key' => $this->apiKey,
            'Content-Type' => 'application/json',
            'Accept' => 'application/json',
        ];
    }

    public function get(string $path, array $query = []): array {
        $resp = $this->http->get($path, [
            'headers' => $this->headers(),
            'query' => $query,
        ]);
        $this->assertOk($resp, $path);
        return json_decode($resp->getBody(), true);
    }

    public function getAnonymous(string $path): array {
        // Dla by-lms-username — wymaga auth, ale możemy użyć master key
        // albo ten endpoint powinien być publiczny (decyzja projektowa)
        $resp = $this->http->get($path, ['headers' => $this->headers()]);
        $this->assertOk($resp, $path);
        return json_decode($resp->getBody(), true);
    }

    public function post(string $path, array $body): array {
        $resp = $this->http->post($path, [
            'headers' => $this->headers(),
            'json' => $body,
        ]);
        $this->assertOk($resp, $path);
        return json_decode($resp->getBody(), true) ?? [];
    }

    public function put(string $path, array $body): array {
        $resp = $this->http->put($path, [
            'headers' => $this->headers(),
            'json' => $body,
        ]);
        $this->assertOk($resp, $path);
        return json_decode($resp->getBody(), true) ?? [];
    }

    public function delete(string $path): void {
        $resp = $this->http->delete($path, ['headers' => $this->headers()]);
        $this->assertOk($resp, $path);
    }

    private function assertOk($resp, string $path): void {
        $status = $resp->getStatusCode();
        if ($status >= 400) {
            $body = json_decode($resp->getBody(), true);
            $detail = $body['detail'] ?? $resp->getReasonPhrase();
            throw new RuntimeException("API error {$status} on {$path}: {$detail}");
        }
    }
}
```

---

## plugin.php — rejestracja hooków LMS

```php
<?php
// Wymagane przez LMS Plus — główny plik pluginu

require_once __DIR__ . '/vendor/autoload.php';
require_once __DIR__ . '/lib/EtaApiClient.php';
require_once __DIR__ . '/lib/EtaSessionAuth.php';
// ... inne require

define('ETA_API_URL', getenv('ETA_API_URL') ?: 'http://localhost:8000');

// Zarejestruj plugin w LMS
$LMS->executeHook('plugin_register', [
    'name'    => 'etanetas-addresses',
    'label'   => 'Adresų sistema',
    'version' => '1.0.0',
]);

// Rejestruj zakładki menu
$LMS->executeHook('menu_item', [
    'label' => 'Pokrycie sieci',
    'icon'  => 'map',
    'url'   => '?m=etanetas-map',
    'permission' => 'etanetas_view',
]);
$LMS->executeHook('menu_item', [
    'label' => 'Adresy',
    'url'   => '?m=etanetas-addresses',
    'permission' => 'etanetas_view',
]);
// ... inne zakładki

// Inicjalizacja klientów
$etaClient = new EtaApiClient(ETA_API_URL);
$etaAuth   = new EtaSessionAuth($LMS, $etaClient);

if ($etaAuth->hasAccess()) {
    $etaClient->setApiKey($etaAuth->getApiKey());
}

// Router pluginu
$module = $_GET['m'] ?? '';
switch ($module) {
    case 'etanetas-map':
        require_once __DIR__ . '/lib/Controllers/MapController.php';
        (new MapController($LMS, $etaClient, $etaAuth))->handle();
        break;
    case 'etanetas-addresses':
        require_once __DIR__ . '/lib/Controllers/AddressController.php';
        (new AddressController($LMS, $etaClient, $etaAuth))->handle();
        break;
    // ... inne
}
```

---

## Gotowe endpointy Python backendu

Wszystkie wymagają nagłówka `X-API-Key: etn_pk_...`

```
# Strefy
GET  /api/v1/admin/zones
     → [{id, name, priority, has_polygon, polygon_geojson (MultiPolygon lub null), created_at}]

GET  /api/v1/admin/zones/{id}/detail
     → {id, name, priority, polygon_geojson, created_at, address_count, offerings: [{...}]}

POST /api/v1/admin/zones
     body: {name, priority, description?, polygon_geojson?}
     → ZoneOut (201)

PUT  /api/v1/admin/zones/{id}
     body: {name?, priority?, description?, polygon_geojson?}

DELETE /api/v1/admin/zones/{id}  (204)

# Offerings stref
GET  /api/v1/admin/zones/{id}/offerings
POST /api/v1/admin/zones/{id}/offerings
     body: {technology_id, status, max_download_mbps, max_upload_mbps, status_since, planned_until?}
PUT  /api/v1/admin/zones/offerings/{id}
     body: {status?, max_download_mbps?, max_upload_mbps?, status_since?, planned_until?}
DELETE /api/v1/admin/zones/offerings/{id}  (204)

# Mapa (GeoJSON dla Leaflet)
GET  /api/v1/admin/map/zones/geojson
     → GeoJSON FeatureCollection stref z offerings summary

GET  /api/v1/admin/map/addresses?bbox=lon1,lat1,lon2,lat2&limit=3000
     → GeoJSON FeatureCollection punktów adresów
     → properties: {rc_code, label, has_address_offering}

# Adresy
POST /api/v1/admin/addresses/search
     body: {q (min 2 znaki), locality_code?, rc_codes?: [int], limit?: 20}
     → [{rc_code, full_address, postal_code, address_type}]

GET  /api/v1/admin/addresses/{rc_code}
     → {rc_code, full_address, postal_code, address_type, locality_code, street_code, house_no, lon, lat}

GET  /api/v1/admin/addresses/{rc_code}/offerings
POST /api/v1/admin/addresses/{rc_code}/offerings
     body: {technology_id, status, max_download_mbps, max_upload_mbps, status_since, planned_until?}
PUT  /api/v1/admin/addresses/offerings/{id}
DELETE /api/v1/admin/addresses/offerings/{id}  (204)

# Bulk operacje
POST /api/v1/admin/bulk/preview
     body: {
       operation: {type:"add_offering", technology_id, status, max_dl_mbps, max_ul_mbps, status_since},
       filter: {rc_codes: [int]}  ← lista zaznaczonych adresów
     }
     → {affected_count, sample: [{address, current, new}], preview_token}

POST /api/v1/admin/bulk/execute
     body: {preview_token}
     → {bulk_operation_id, modified_count}

POST /api/v1/admin/bulk/{id}/rollback  (204)
GET  /api/v1/admin/bulk-operations

# Technologie (dla dropdownów)
GET  /api/v1/admin/technologies       → [{id, variant_code, display_name, type_id, active}]
GET  /api/v1/admin/technology-types   → [{id, code, display_name, public_name, sort_order, active}]

# Użytkownicy
GET  /api/v1/admin/me                             → {id, username, email, role, lms_username}
GET  /api/v1/admin/users                          → lista (admin only)
POST /api/v1/admin/users                          body: {username, email, role}
PUT  /api/v1/admin/users/{id}                     body: {email?, role?, active?, lms_username?}
DELETE /api/v1/admin/users/{id}                   (204, soft-delete)
POST /api/v1/admin/users/{id}/api-keys            body: {name}  → {raw_key, ...} (TYLKO RAZ)
GET  /api/v1/admin/users/{id}/api-keys
DELETE /api/v1/admin/api-keys/{id}               (204, revoke)
GET  /api/v1/admin/users/by-lms-username/{login} → user lub 404

# Audit
GET  /api/v1/admin/audit-log?entity_type=&entity_id=&since=&until=&limit=50
GET  /api/v1/admin/addresses/{rc_code}/history
```

**Typy statusów offering:** `available` | `planned` | `under_construction` | `unavailable`

---

## UX — Ekran mapy (główny, implementuj jako pierwszy)

Plik: `templates/map.tpl` + `assets/js/eta-map.js`

### Układ

```
┌── LMS nawigacja (górny pasek LMS) ─────────────────────────────┐
│ Etanetas: [Mapa] [Adresy] [Strefy] [Technologie] [Użytkownicy] │
├────────────────────────────────────────────────────────────────┤
│ [+ Nowa strefa]  [Warstwy ▾]  [Szukaj adresu... 🔍]           │
├──────────────────────────────────┬─────────────────────────────┤
│                                  │ SIDEBAR (320px, scrollable)  │
│  MAPA (Leaflet, pełna wysokość)  │                             │
│                                  │  [pusty gdy nic nie kliknięte│
│  🟢 strefy available             │  lub szczegóły strefy/adresu]│
│  🟡 strefy planned               │                             │
│  🔵 punkty adresów (zoom ≥ 15)  │                             │
│                                  │                             │
│  Toolbar Leaflet.draw:           │                             │
│  [✏️ Rysuj] [✂️ Edytuj] [🗑️]    │                             │
│                                  │                             │
├──────────────────────────────────┴─────────────────────────────┤
│ Legenda: ■ GPON avail  ░ GPON plan  ▪ Wireless  ▫ LTE         │
└────────────────────────────────────────────────────────────────┘
```

### Kolory stref (implementuj w eta-map.js)

```javascript
function zoneStyle(zone) {
    // zone.offerings = [{status, technology_type, ...}]
    const priority = {available: 3, under_construction: 2, planned: 1, unavailable: 0};
    const colorMap = {
        FIBER: '#22c55e', ETHERNET: '#3b82f6',
        WIRELESS: '#f97316', LTE: '#a855f7'
    };

    // Weź offering z najwyższym statusem
    const top = (zone.offerings || []).sort((a,b) =>
        (priority[b.status]||0) - (priority[a.status]||0)
    )[0];

    const baseColor = top ? (colorMap[top.technology_type] || '#6b7280') : '#9ca3af';
    const isPlanned = top?.status === 'planned' || top?.status === 'under_construction';

    return {
        color: baseColor,
        weight: 2,
        fillColor: baseColor,
        fillOpacity: 0.2,
        dashArray: isPlanned ? '8, 4' : null,
    };
}
```

### Sidebar — kliknięcie na strefę

PHP endpoint: `GET /lms-plugin/zones/{id}/sidebar` zwraca HTML fragment

```html
{* templates/partials/zone_sidebar.tpl *}
<div class="eta-sidebar">
  <div class="eta-sidebar-header">
    <h3>{$zone.name}</h3>
    <span class="eta-badge">Priorytet: {$zone.priority}</span>
    <span class="eta-badge">{$zone.address_count} adresų</span>
  </div>

  <div class="eta-offerings">
    {foreach $zone.offerings as $off}
    <div class="eta-offering eta-status-{$off.status}">
      <span class="eta-dot"></span>
      <strong>{$off.public_name}</strong> · {$off.status}
      <div class="eta-speeds">{$off.max_download_mbps}↓ / {$off.max_upload_mbps}↑ Mbps</div>
      {if $off.planned_until}<div class="eta-until">do {$off.planned_until}</div>{/if}
      <button class="eta-btn-sm"
        hx-get="/lms-plugin/zones/{$zone.id}/offering/{$off.id}/edit"
        hx-target="closest .eta-offering"
        hx-swap="outerHTML">Redaguoti</button>
    </div>
    {/foreach}
  </div>

  <div class="eta-sidebar-actions">
    <button hx-get="/lms-plugin/zones/{$zone.id}/offering/new"
            hx-target=".eta-offerings" hx-swap="beforeend">
      + Pridėti paslaugą
    </button>
    <button onclick="etaMap.startEditZone('{$zone.id}')">Redaguoti strefą</button>
    <button hx-delete="/lms-plugin/zones/{$zone.id}"
            hx-confirm="Ištrinti šią zoną?" hx-on::after-request="etaMap.removeZone('{$zone.id}')">
      Ištrinti
    </button>
  </div>
</div>
```

### Sidebar — kliknięcie na adres (popup)

```html
{* templates/partials/address_popup.tpl *}
<div class="eta-popup">
  <strong>{$address.full_address}</strong>
  <small>RC: {$address.rc_code} · {$address.address_type}</small>

  {if $address.offerings}
    {foreach $address.offerings as $off}
    <div class="eta-coverage eta-status-{$off.status}">
      ✓ {$off.public_name} — {$off.status}
      <br>{$off.max_download_mbps}↓/{$off.max_upload_mbps}↑ Mbps
    </div>
    {/foreach}
  {else}
    <div class="eta-no-coverage">❌ Brak pokrycia</div>
    <button hx-get="/lms-plugin/addresses/{$address.rc_code}/offering/new"
            hx-target=".eta-popup" hx-swap="innerHTML">
      + Przypisz ręcznie
    </button>
  {/if}
</div>
```

### Rysowanie nowej strefy (formularz po narysowaniu)

```html
{* templates/partials/zone_new_form.tpl — wstrzykiwany do sidebaru *}
<div class="eta-sidebar eta-new-zone" x-data="newZoneForm()">
  <h3>Nowa strefa</h3>

  <div class="eta-field">
    <label>Nazwa</label>
    <input type="text" x-model="form.name" placeholder="np. Eišiškių g. 2024">
  </div>
  <div class="eta-field">
    <label>Priorytet</label>
    <input type="number" x-model.number="form.priority" value="100">
    <small>Wyższy wygrywa gdy strefy się nakładają</small>
  </div>

  <div class="eta-offering-builder">
    <h4>Paslauga (dodaj teraz lub później)</h4>
    <select x-model="offering.technology_id">
      <option value="">-- wybierz --</option>
      {foreach $technologies as $t}
        <option value="{$t.id}">{$t.display_name}</option>
      {/foreach}
    </select>
    <select x-model="offering.status">
      <option value="available">available</option>
      <option value="planned">planned</option>
      <option value="under_construction">under_construction</option>
    </select>
    <input type="number" x-model.number="offering.max_download_mbps" placeholder="↓ Mbit/s">
    <input type="number" x-model.number="offering.max_upload_mbps" placeholder="↑ Mbit/s">
    <input type="date" x-model="offering.status_since">
    <input type="date" x-model="offering.planned_until" placeholder="Planuojama iki (opcjonalnie)">
  </div>

  <div class="eta-field">
    <em x-text="`Pokryte adresy: ${addressCount}`"></em>
  </div>

  <div class="eta-actions">
    <button @click="save()" :disabled="!form.name">Išsaugoti</button>
    <button @click="cancel()">Atšaukti</button>
  </div>
</div>

<script>
function newZoneForm() {
  return {
    form: { name: '', priority: 100 },
    offering: { technology_id: '', status: 'available', max_download_mbps: 1000, max_upload_mbps: 500, status_since: new Date().toISOString().split('T')[0], planned_until: '' },
    addressCount: window.etaMap?.previewAddressCount || 0,
    async save() {
      const zone = await window.etaMap.saveNewZone(this.form);
      if (zone && this.offering.technology_id) {
        await window.etaMap.addOffering(zone.id, this.offering);
      }
    },
    cancel() { window.etaMap.cancelDraw(); }
  }
}
</script>
```

---

## UX — Ekran tabeli adresów

Plik: `templates/addresses.tpl`

Bulk operations flow:
1. Szukaj → tabela wyników
2. Zaznacz checkboxy → pojawia się action bar
3. Kliknij "Grupinė operacija" → wybierz: Pridėti technologiją
4. Formularz → "Peržiūrėti" → modal z preview
5. Zatwierdź → execute → toast "Pakeista N adresų [Anuliuoti]" (15 min)

Anuliuoti → `POST /api/v1/admin/bulk/{id}/rollback`

---

## UX — Ekran zarządzania użytkownikami (krytyczny dla LMS integracji)

Plik: `templates/users.tpl`

Każdy wiersz użytkownika musi mieć pole "LMS login":

```
| Username | Email          | Rola   | LMS login          | Klucze | Akcje |
|----------|----------------|--------|--------------------|--------|-------|
| jonas    | j@etanetas.lt  | admin  | jonas.kazlauskas   | 2 aktywne | [✏️] |
| maria    | m@etanetas.lt  | editor | [nie powiązany]    | 1 aktywna | [✏️] |
```

Przy edycji użytkownika: pole `lms_username` → `PUT /api/v1/admin/users/{id}` z `{lms_username: "login.lms"}`.

Sekcja "API klucze":
- Lista aktywnych kluczy (nazwa, data, last_used_at)
- [+ Nowy klucz] → `POST /api/v1/admin/users/{id}/api-keys` → **pokaż raw key raz** w modalu
- [Odwołaj] → `DELETE /api/v1/admin/api-keys/{id}`

---

## Konfiguracja CORS

Python backend musi mieć origin LMS serwera w `CORS_ORIGINS`. Dodaj do `.env` backendu:

```env
CORS_ORIGINS=https://etanetas.lt,https://lms.etanetas.lt,http://localhost:8080
```

(LMS Plus typowo chodzi na porcie 80/443 lub osobnym)

---

## Zacznij od tego (kolejność implementacji)

1. **`composer.json`** + `vendor/` z Guzzle
2. **`EtaApiClient.php`** — Guzzle wrapper
3. **`plugin.php`** — rejestracja hooków, basic routing, setup flow (wklejanie API key)
4. **`MapController.php`** + **`map.tpl`** — podstawowa mapa z wczytywaniem stref
5. **`assets/js/eta-map.js`** — Alpine komponent: loadZones, loadAddresses, click events
6. Sidebar strefy (kliknięcie → szczegóły)
7. Rysowanie nowej strefy + formularz + zapis
8. Popup adresu (kliknięcie → pokrycie)
9. `AddressController.php` + `addresses.tpl` — tabela + bulk ops
10. `UserController.php` + `users.tpl` — zarządzanie + LMS username powiązanie
11. Pozostałe ekrany (zones list, technologies, audit)

---

## Ważne szczegóły

**Konwersja Polygon → MultiPolygon:** Leaflet.draw rysuje `Polygon`, backend oczekuje `MultiPolygon`. W JS przed wysłaniem:
```javascript
if (geojson.type === 'Polygon') {
    geojson = { type: 'MultiPolygon', coordinates: [geojson.coordinates] };
}
```

**Wyświetlanie stref bez adresów:** Na początku baza może mieć 0 stref. Mapa powinna mieć state "Brak stref — narysuj pierwszą strefę →" z instrukcją.

**Zoom threshold dla adresów:** Załaduj punkty adresów tylko przy zoom ≥ 15. Przy mniejszym zoomie — zbyt wiele punktów, za wolne.

**HTMX vs Alpine:** HTMX do prostych operacji server-side (formularze CRUD bez złożonego state). Alpine do mapy i tabeli adresów (złożony reaktywny state: zaznaczenia, preview tokens, timery undo).

**Błędy API:** Każde wywołanie API może zwrócić 401 (wygasły klucz) → przekieruj do setup screen. 403 (brak roli) → pokaż komunikat.

**address_count w strefie:** Endpoint `/detail` liczy to live — może być wolne przy pierwszym otwarciu strefy z dużym poligonem. OK dla MVP.
