# Next.js frontend — plan implementacji

## Cel

Pełnoprawny frontend webowy dla testowania backendu Etanetas. Nie LMS plugin, nie
mockup — działająca aplikacja do codziennej pracy z mapą stref, adresami i operacjami.

Po wdrożeniu LMS pluginu (PHP) ta aplikacja zostaje jako:
- środowisko testowe / developerskie
- alternatywny panel admin dla kogoś kto nie używa LMS
- referencyjna implementacja UX dla LMS pluginu

---

## Stack technologiczny

| Warstwa | Technologia | Powód |
|---|---|---|
| Framework | **Next.js 15 (App Router)** | Modern, React Server Components, file-based routing |
| Język | **TypeScript** | Typy z backendu → klient bez błędów |
| Styling | **Tailwind CSS 4** | Szybkie prototypowanie, utility-first |
| Komponenty UI | **shadcn/ui** | Copy-paste, ty kontrolujesz kod, brak narzuconych decyzji |
| Data fetching | **TanStack Query v5** | Cache, refetch, optimistic updates, dev tools |
| Mapa | **react-leaflet 4** + **leaflet-draw** | Wrapper dla Leafleta z React lifecycle |
| Stan globalny | **Zustand** | Lekki (3kB), bez boilerplate Redux |
| Formularze | **react-hook-form + zod** | Walidacja typowana, mała |
| Toasty | **sonner** | Akcesybilne, prosty API |
| Ikony | **lucide-react** | Spójne, drzewo-shake'owalne |
| HTTP klient | **fetch + custom wrapper** | Brak axios, nowoczesne API |
| Lint | **Biome** | Szybszy niż ESLint+Prettier, jeden tool |

**Brak:** Redux, Sass, styled-components, axios, Jest, MUI, Material UI, AntD.

---

## Organizacja projektu (po zmianach)

Aktualnie wszystko jest w roocie. Proponuję:

```
etanetas-coverage/
├── backend/                ← przeniesione: app/, etl/, alembic/, tests/, pyproject.toml, alembic.ini, .env, compose.yml
│   ├── app/
│   ├── etl/
│   ├── alembic/
│   ├── tests/
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── .env
│   ├── compose.yml          ← postgres docker
│   └── README.md
│
├── web/                    ← nowy: Next.js frontend
│   ├── app/                 # App Router
│   │   ├── (auth)/setup/   # ekran konfiguracji API key
│   │   ├── (dashboard)/
│   │   │   ├── layout.tsx
│   │   │   ├── page.tsx                # dashboard
│   │   │   ├── map/page.tsx            # mapa (główny)
│   │   │   ├── zones/page.tsx
│   │   │   ├── addresses/page.tsx
│   │   │   ├── technologies/page.tsx
│   │   │   ├── users/page.tsx
│   │   │   ├── audit/page.tsx
│   │   │   └── operations/page.tsx
│   │   ├── api/                       # Next.js API routes (proxy)
│   │   │   └── proxy/[...path]/route.ts
│   │   ├── layout.tsx
│   │   └── globals.css
│   ├── components/
│   │   ├── ui/              # shadcn (button, dialog, table, etc.)
│   │   ├── map/             # MapView, ZoneLayer, AddressLayer, DrawControl
│   │   ├── zones/           # ZoneSidebar, ZoneForm, ZoneList
│   │   ├── addresses/       # AddressTable, AddressFilters, BulkActions
│   │   ├── bulk/            # BulkPreviewModal, OperationCard
│   │   └── layout/          # Sidebar, TopNav, Breadcrumb
│   ├── lib/
│   │   ├── api/             # generated types + client functions
│   │   │   ├── client.ts    # fetch wrapper z X-API-Key
│   │   │   ├── zones.ts     # listZones(), getZoneDetail(), createZone()
│   │   │   ├── addresses.ts
│   │   │   ├── bulk.ts
│   │   │   ├── hierarchy.ts
│   │   │   └── types.ts     # auto-generated z OpenAPI
│   │   ├── stores/
│   │   │   ├── auth.ts      # zustand: apiKey, apiUrl, user
│   │   │   └── map.ts       # selectedZone, drawState, filters
│   │   ├── hooks/
│   │   │   ├── useZones.ts  # TanStack queries
│   │   │   ├── useAddresses.ts
│   │   │   └── useBulk.ts
│   │   └── utils/
│   │       ├── geojson.ts   # Polygon ↔ MultiPolygon konwersja
│   │       └── colors.ts    # status → kolor mapping
│   ├── public/
│   ├── package.json
│   ├── tsconfig.json
│   ├── tailwind.config.ts
│   ├── biome.json
│   ├── next.config.ts
│   ├── .env.local           # NEXT_PUBLIC_API_URL=http://localhost:8000
│   └── README.md
│
├── docs/                   # bez zmian: TZ, README, spec
│   ├── etanetas_adresu_sistema_TZ_v2.md
│   ├── README.md
│   ├── lms-plugin-spec.md
│   ├── lms-plugin-ai-prompt.md
│   └── frontend-plan.md     ← ten plik
│
├── .gitignore               # rozszerzony o web/node_modules, .next, etc.
├── CLAUDE.md                # zaktualizowany pod nowy layout
└── README.md                # root — linki do backend/ i web/
```

**Powód restrukturyzacji:** rozdzielenie języków/runtime. Backend (Python) i frontend
(Node.js) mają osobne dependency tree, osobne komendy, osobne CI. Wspólne repo = łatwe
trzymanie ich synchronizowanych ale niezależnych.

---

## Migracja: jak przejść z obecnej struktury

Komenda (do uruchomienia raz):

```bash
# w roocie projektu
mkdir backend
git mv app etl alembic tests pyproject.toml uv.lock alembic.ini compose.yml backend/
git mv .env .env.example backend/   # jeśli istnieją
# .pre-commit-config.yaml zostaje w roocie (obejmuje cały projekt)

# stworzyć Next.js w web/
cd /tmp && npx create-next-app@latest etanetas-web --typescript --tailwind --app --src-dir=false --eslint=false
mv /tmp/etanetas-web /home/robertas/workspace/robertas/etanetas-coverage/web

# aktualizacje:
# - CLAUDE.md: ścieżki app/ → backend/app/, etl/ → backend/etl/
# - alembic ini: ścieżka migracji
# - docker compose: working_dir
# - testy CI: cd backend && pytest
```

Po migracji każdy frontend dev pracuje w `web/`, każdy backend dev w `backend/`.

---

## Strony i features (kolejność implementacji)

### 1. `/setup` — pierwsze uruchomienie

Pusty stan + formularz konfiguracji:

```
┌──────────────────────────────────────────┐
│  ⚡ Etanetas — pierwsze uruchomienie     │
│                                          │
│  API URL                                 │
│  [http://localhost:8000_____________]    │
│                                          │
│  API Key                                 │
│  [etn_pk_***________________________]    │
│                                          │
│  (Wygeneruj kluczem CLI:                 │
│   uv run python -m app.cli create-key)  │
│                                          │
│  [Połącz]                                │
└──────────────────────────────────────────┘
```

Po zatwierdzeniu: testuje `GET /me`, jeśli OK → zapisuje w localStorage → redirect na `/`.

### 2. `/` — Dashboard

Kafle z metryk + lista do działania:

```
┌─────────────────────────────────────────────────────────────────────┐
│ Dashboard                                                           │
├─────────────────────────────────────────────────────────────────────┤
│ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐                │
│ │ Adresów  │ │ Pokrytych│ │ Stref    │ │ Operacji │                │
│ │ 1 126K   │ │ 15 (0%)  │ │ 2        │ │ 8        │                │
│ └──────────┘ └──────────┘ └──────────┘ └──────────┘                │
│                                                                     │
│ ┌──────────────────────────┐ ┌──────────────────────────────────┐  │
│ │ Pokrycie po statusie     │ │ Top miasta bez pokrycia          │  │
│ │ ████ available  2        │ │ 1. Vilnius      80 592 adresów  │  │
│ │                          │ │ 2. Kaunas       51 320          │  │
│ │ [chart]                  │ │ 3. Šiauliai     20 384          │  │
│ └──────────────────────────┘ │ → kliknij → mapa centrowana       │  │
│                              └──────────────────────────────────┘  │
│                                                                     │
│ Ostatnie operacje                                                   │
│ ▸ add_offering · 2 addr · 2 min temu · robertas · [Anuluj]         │
│ ▸ change_offering · 1 addr · 5 min temu · robertas                 │
└─────────────────────────────────────────────────────────────────────┘
```

API: `GET /coverage/stats`, `GET /bulk-operations`.

### 3. `/map` — Mapa pokrycia (GŁÓWNY EKRAN)

Lewy panel (`260px`): warstwy + filtry.
Główny obszar: mapa Leaflet (pełny ekran).
Prawy panel (`360px`, slide-in): szczegóły strefy/adresu.

```
┌─Sidebar─┬──── MAPA ───────────────────────────┬─Detail (slide-in)─┐
│ Warstwy │                                     │                   │
│ ☑ Strefy│   [Leaflet OSM tiles]              │  Eišiškės centrum │
│ ☑ Adresy│                                     │  Priorytet: 100   │
│         │   🟢🟡 polygons                     │  Adresów: 234     │
│ Tech    │   🔵 dots (zoom ≥ 15)              │                   │
│ ☑ FIBER │                                     │  Paslaugos:       │
│ ☑ WLAN  │   [⊕ Nowa strefa]                  │  ●🟢 GPON avail   │
│         │   [⌖ Edytuj]                       │     1000/500      │
│ Status  │                                     │                   │
│ ☑ avail │                                     │  [Edytuj]         │
│ ☑ plan  │                                     │  [+ Paslauga]    │
│         │                                     │  [Usuń]           │
│ [🔍]    │                                     │                   │
└─────────┴─────────────────────────────────────┴───────────────────┘
```

**Interakcje:**
- Top bar: globalny search adresu (autocomplete, fly-to-marker)
- Click polygon → otwiera prawy panel z `GET /zones/{id}/detail`
- Click punkt adresu → popup + opcja "+ Override"
- "Nowa strefa" → tryb rysowania → polygon → formularz w prawym panelu → POST
- Edytuj → tryb edycji wierzchołków → drag → PUT
- Shift+drag na mapie → rysuj prostokąt → wszystkie adresy w środku zaznaczone → bulk dropdown

API: `GET /map/zones/geojson`, `GET /map/addresses?bbox=`, `POST /zones`, `PUT /zones/{id}`, `POST /map/in-polygon`.

### 4. `/addresses` — Tabela adresów + bulk

Klasyczny CRUD z cascading filters i bulk ops.

```
┌─────────────────────────────────────────────────────────────────────┐
│ Adresy                                                              │
├─────────────────────────────────────────────────────────────────────┤
│ Apskritis▾ Sav.▾ Gyvenv.▾ Gatvė▾ │ [🔍 Szukaj]                    │
│ Tech▾ Status▾ ☐Tik be pokrycia    │ [Wyczyść filtry]                │
├─────────────────────────────────────────────────────────────────────┤
│ ☑ Adresas              Pašt.    Tech                  Akcje        │
│ ☑ Vilniaus g. 12       LT-01234 🟢GPON 🟡WLAN          ▸ Szczegóły │
│ ☑ Vilniaus g. 14       LT-01234 🟢GPON                 ▸           │
│ ☐ Medžių g. 5          LT-01235 (brak)                 ▸           │
│ ☐ ▸ rozwinięty                                                     │
│      • GPON · available · 1000/500 · od 2024-03 · zona X · [Edytuj]│
│      • Wireless · planned · 100/50 · do 2026-09 · override · [Del] │
│      [+ Dodaj paslaugą]                                             │
├─────────────────────────────────────────────────────────────────────┤
│ Zaznaczono: 2 z 47   [Bulk ▾ Pridėti│Pakeisti│Pašalinti] [Wyczyść] │
└─────────────────────────────────────────────────────────────────────┘
```

**Bulk flow:**
1. Zaznacz adresy → bottom toolbar
2. Wybierz operację z dropdown
3. Formularz w modal (tech, status, speeds)
4. "Peržiūrėti" → preview modal (affected count, sample)
5. "Vykdyti" → toast `Pakeista N adresų [Atšaukti 15min]`
6. Klik undo → POST `/bulk/{id}/rollback`

API: `POST /addresses/search`, `GET /addresses/{rc}/offerings`, `POST/PUT/DELETE /addresses/.../offerings`, `POST /bulk/preview`, `POST /bulk/execute`, `POST /bulk/{id}/rollback`, hierarchy endpoints.

### 5. `/zones` — Lista stref (alternatywny widok)

Tabela dla adminów którzy nie chcą mapy.

```
┌─────────────────────────────────────────────────────────────────────┐
│ Strefy pokrycia                              [+ Nowa strefa]        │
├─────────────────────────────────────────────────────────────────────┤
│ Pavadinimas         Prior  Adresų  Paslaugos          Akcje        │
│ Eišiškės centrum    100    234     🟢GPON 🟠WLAN     [✏️][🗺️][🗑️] │
│ Eišiškių g. 1-50    200    47      🟢GPON             [✏️][🗺️][🗑️] │
│ Šalčininkai centrum 150    892     🟢GPON 🟢xGPON     [✏️][🗺️][🗑️] │
├─────────────────────────────────────────────────────────────────────┤
│ ▸ rozwinięty: pełna lista offerings + przyciski edycji              │
└─────────────────────────────────────────────────────────────────────┘
```

`[🗺️]` → link do `/map?zone={id}` (centruje na strefie).
`[✏️]` → inline edit nazwy/priorytetu (bez polygonu — to robi się na mapie).

### 6. `/technologies` — Katalog technologii

```
Typy technologii (read-only z migracji + edycja display_name)
┌──────────────────────────────────────────────┐
│ Kod      Display       Public name    Aktyw │
│ FIBER    Šviesolaidis  Šviesolaidis   ✓    │
│ ETHERNET Ethernet      Ethernet       ✓    │
│ ...                                         │
└──────────────────────────────────────────────┘

Warianty (CRUD)               [+ Nowa]
┌──────────────────────────────────────────────┐
│ Kod      Display       Max ↓/↑     Aktywny  │
│ gpon     GPON 2.5G     2500/1250   ✓ [✏️]  │
│ xgpon    XG-PON        10000/10000 ✓ [✏️]  │
└──────────────────────────────────────────────┘
```

### 7. `/users` — Użytkownicy + API keys

```
Lista użytkowników                            [+ Nowy]
┌────────────────────────────────────────────────────────┐
│ Username  Email          Rola   LMS login    Klucze   │
│ robertas  r@etanetas.lt  admin  robertas     2 [▾]   │
│   ▸ rozwinięty:                                       │
│     • initial · stworzony 2026-05-19 · użyty 5min temu│
│     • main · stworzony 2026-05-21 · [Revoke]         │
│     [+ Nowy klucz] → modal pokazuje raw key 1×       │
└────────────────────────────────────────────────────────┘
```

### 8. `/audit` — Audit log

```
Filtry: Typ▾ User▾ Data od-do  Entity ID [_________]

Historia                                          200 entries
┌────────────────────────────────────────────────────────────────┐
│ ▸ 14:32 robertas service_zone create "Eišiškės centrum"      │
│ ▸ 14:30 robertas address_offering update {status:planned→available} │
│ ▸ 14:25 robertas bulk_operation execute add_offering ×47     │
│ ▸ 14:20 jonas    user_login                                  │
└────────────────────────────────────────────────────────────────┘
```

### 9. `/operations` — Historia bulk operations

```
Operacje grupowe                              Filtruj: ☐ tylko aktywne

┌─────────────────────────────────────────────────────────────────┐
│ Type            Adresów  Data         Status       Akcje       │
│ add_offering    47       2026-05-21   ✓ executed   [Anuluj]    │
│ change_offering 12       2026-05-21   ✓ executed   [Anuluj]    │
│ remove_offering 5        2026-05-20   ⊘ rolled back            │
│ add_offering    234      2026-05-20   ✓ executed              │
└─────────────────────────────────────────────────────────────────┘
```

---

## Auth flow

**Bez backendu auth na froncie** — używamy bezpośrednio API key z localStorage.

```ts
// lib/stores/auth.ts
export const useAuth = create<AuthStore>((set) => ({
  apiKey: typeof window !== 'undefined' ? localStorage.getItem('eta_key') : null,
  apiUrl: typeof window !== 'undefined' ? localStorage.getItem('eta_url') : 'http://localhost:8000',
  setCreds: (key, url) => {
    localStorage.setItem('eta_key', key)
    localStorage.setItem('eta_url', url)
    set({ apiKey: key, apiUrl: url })
  },
  clear: () => {
    localStorage.removeItem('eta_key')
    set({ apiKey: null })
  },
}))
```

Middleware Next.js (`middleware.ts`):
```ts
// Jeśli nie ma klucza w sesji → redirect do /setup
// (state w localStorage więc faktycznie sprawdza klient-side w layoucie)
```

W praktyce: `(dashboard)/layout.tsx` sprawdza `useAuth().apiKey` — jeśli null, renderuje redirect do `/setup`.

---

## Type safety end-to-end

Backend FastAPI generuje OpenAPI schema na `/openapi.json`. Używamy `openapi-typescript`
do wygenerowania typów TypeScript:

```bash
# package.json
"scripts": {
  "gen-types": "npx openapi-typescript http://localhost:8000/openapi.json -o lib/api/types.ts"
}
```

Wynik: `lib/api/types.ts` z typami dla wszystkich endpointów + schematów. Frontend
zawsze zsynchronizowany z backendem.

W komponencie:
```ts
import { ZoneOut } from '@/lib/api/types'

const { data } = useQuery<ZoneOut[]>({
  queryKey: ['zones'],
  queryFn: () => apiGet('/api/v1/admin/zones'),
})
// data jest pełnie otypowane
```

---

## Konfiguracja CORS

Backend już ma localhost w `cors_origins`. Dodać `http://localhost:3000` jeśli brakuje:

```python
# backend/app/config.py
cors_origins: list[str] = [
    "https://etanetas.lt",
    "https://www.etanetas.lt",
    "http://localhost:3000",  # Next.js dev
]
```

Dla produkcji frontu (jeśli go wdrażamy) — dodać prawdziwy domain.

---

## Kolejność implementacji (do roboty kontekst Next.js chata)

**Faza 0 — restruktura** (do zrobienia raz, w głównym czacie):
1. Przeniesienie backendu do `backend/`
2. Aktualizacja CLAUDE.md, alembic.ini paths, README
3. Stworzenie pustego `web/` z `create-next-app`
4. Commit

**Faza 1 — fundament (1-2 dni):**
1. shadcn/ui setup (init, button, dialog, table, form, dropdown)
2. TanStack Query provider + API client (`lib/api/client.ts`)
3. Zustand auth store + setup page
4. Layout z sidebar nawigacją
5. Generowanie typów OpenAPI

**Faza 2 — dashboard + zarządzanie (2 dni):**
1. Dashboard (`/`) z coverage stats
2. Technologies CRUD
3. Users CRUD + API keys

**Faza 3 — adresy + bulk (3 dni):**
1. Cascading filters (counties → muni → locality → street)
2. Address table z paginacją
3. Bulk action toolbar
4. Preview modal + execute + undo toast
5. Address detail (offerings list inline)

**Faza 4 — mapa (3-4 dni):**
1. React-Leaflet wrapper + base map
2. Zone layer (GeoJSON z `/map/zones/geojson`)
3. Address layer z bbox-driven loading
4. Zone sidebar (click polygon)
5. Address popup (click point)
6. Draw polygon → form → POST zone
7. Edit polygon (vertex dragging)
8. In-polygon select → bulk

**Faza 5 — pozostałe (1-2 dni):**
1. Zones list (`/zones`)
2. Audit log (`/audit`)
3. Operations history (`/operations`)

**Faza 6 — polerka (1 dzień):**
1. Loading states / skeletons
2. Error boundaries
3. Empty states
4. Keyboard shortcuts (Ctrl+K dla search)
5. Dark mode (opcjonalnie)

---

## Kluczowe decyzje projektowe

**1. Proxy przez Next.js API routes czy bezpośrednio?**

Wybór: **bezpośrednio z klienta do FastAPI** dla dev. W produkcji można dodać proxy
przez `/api/proxy/[...path]` żeby API key zostawał server-side i nie był widoczny
w localStorage przeglądarki.

MVP: localStorage + CORS. Production: proxy + cookies.

**2. RSC vs Client Components?**

Większość stron to interaktywny CRUD — głównie client components z `'use client'`.
Tylko layout i statyczne strony serwerowe. Nie tracimy SEO bo to admin panel
(nie indeksowany).

**3. Routing parameters w mapie?**

`/map?zone={id}` lub `/map?lat=...&lng=...&zoom=...` — query params, łatwe do linkowania.
Niedeep-link tylko podstawowy state.

**4. Real-time updates?**

Nie w MVP. Po każdej mutacji TanStack Query invalidate'uje cache, dane się odświeżają.
WebSockets/SSE odraczamy do wersji 2 jeśli będzie potrzeba multi-user collab.

**5. i18n?**

MVP po polsku + litewsku w UI labels (etanetas to litewska firma). Później `next-intl`
jeśli będzie EN. Status enums (`available`, `planned`) zostają po angielsku (z backendu).

---

## Co zostaje na później (nie w MVP)

- Real-time multi-user (presence, collab cursors)
- Eksport raportów (PDF/CSV) z `/coverage/stats`
- Mobilna wersja (mapa działa na touch, reszta scrolluje)
- Dark mode
- Notyfikacje push (np. "ETL sync failed")
- Multi-tenant (różne ISP w jednej instancji)
- Public customer search (Stage 6 — to osobny mini-frontend)

---

## Testy

**Frontend:** smoke testy E2E z Playwright (3-4 scenariusze critical path):
1. Setup → wpisz klucz → dashboard się ładuje
2. Stwórz strefę z polygonem na mapie → pojawia się w liście
3. Wyszukaj adres → bulk add offering → preview → execute → undo
4. Zarządzanie użytkownikami → utwórz user → wygeneruj klucz → revoke

Unit testy: tylko utils (`geojson.ts`, color logic). Komponenty nie — to dobrze
przetestowane przez E2E.

---

## Definicja "gotowe"

- ✅ Wszystkie 9 stron działają z prawdziwym backendem
- ✅ Mapa: tworzenie/edycja/usuwanie stref przez UI
- ✅ Bulk: add/change/remove + undo
- ✅ Dashboard: live metryki
- ✅ Type safety: kompiluje się bez błędów TypeScript
- ✅ Lint: `bun biome check` zero błędów
- ✅ E2E: 4 scenariusze przechodzą
- ✅ Działa w Chrome, Firefox (Safari nice-to-have)
- ✅ README w `web/` z `bun install && bun dev`
