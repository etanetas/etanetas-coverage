# Model utrzymania pokrycia — adres jako jedyne źródło prawdy, auto-zony per obszar, mapa jako edytor

Data: 2026-06-11
Status: approved design
Rozszerza/nadpisuje: `2026-06-11-auto-zones-design.md` (jedna auto-zona per
technologia → osobna zona per spójny obszar; naprawa przecieku stref do
availability).

Zakres obejmuje dwa repozytoria: API (`etanetas-coverage`) i plugin LMS
(`LMSEtaCoveragePlugin`). Etapy 1, 2, 5 — API; etapy 3, 4 — plugin.

## Decyzje (brainstorming 2026-06-11)

1. **Dostępność = wyłącznie oferty adresowe.** Strefy (auto i ręczne) nie
   wpływają na publiczny endpoint availability. LTE/radio również deklarowane
   per-adres (bulkiem po obszarze), nie strefą.
2. **Auto-zony to czysta wizualizacja** — po jednej strefie na spójny obszar
   per technologia, przeliczane po każdej zmianie ofert. Edycja polygonu
   auto-zony i konwersja auto→manual: odrzucone (tworzyłyby drugie źródło
   prawdy i dryf danych).
3. **Nazwy auto-obszarów:** generowane z dominującej miejscowości
   (`Auto: GPON — Jašiūnai`), z opcjonalną nazwą własną (`custom_name`),
   która przeżywa przeliczenia.
4. **Mapa LMS jest głównym edytorem pokrycia:** rysowanie obszaru →
   bulk add/change/**remove** ofert adresowych w środku → auto-zony same się
   przerysowują. Narysowany polygon to narzędzie zaznaczania, nie zapisywany
   byt.
5. **Moduł zarządzania strefami ręcznymi (`etacoveragezones`, pkt E roadmapy
   pluginu): skreślony.** Strefy `manual` zostają w bazie jako uśpiony koncept
   bez UI i bez wpływu na availability.

## Etap 1 — uszczelnienie modelu (API, małe)

- `_AVAILABILITY_SQL` w `app/api/v1/public/addresses.py`: usunąć CTE
  `zone_offerings_filtered` i `combined` — wynik liczy się tylko z
  `address_offerings`. Naprawia to przeciek: 150-metrowy bufor auto-zony
  pokazywał sąsiadom technologię jako dostępną z prędkością `MAX` całej sieci.
- `ZoneOut`/`ZoneDetail` (`app/schemas/zones.py`): dodać pole `source`.
- GeoJSON stref (`/admin/map/zones/geojson`): dodać `source` do `properties`
  (potrzebne do filtra na mapie LMS).
- `PATCH /admin/zones/{id}` dla `source='auto'`: dozwolona wyłącznie zmiana
  `custom_name` (etap 2); zmiana `polygon_geojson`/`priority`/`name` na auto
  zonie → 422. Zastępuje dotychczasowe „dozwolone, ale rebuild nadpisze".

## Etap 2 — auto-zony per spójny obszar (API, sedno)

### Model danych (alembic)

- `service_zones.custom_name TEXT NULL` — tylko dla stref auto; nazwa
  efektywna = `COALESCE(custom_name, name)`. `name` pozostaje generowane.

### Algorytm rebuildu (per technologia, w `app/auto_zones.py`)

1. Advisory lock per technologia (bez zmian).
2. Zamiast jednej unii: `ST_Dump(ST_Union(buffers))` → lista spójnych
   komponentów (polygonów).
3. Per komponent: dominująca miejscowość = miejscowość z największą liczbą
   adresów z ofertą `available` wewnątrz komponentu. Nazwa generowana:
   `Auto: {tech.display_name} — {locality}`; przy kolizji nazw w ramach
   technologii sufiks ` (2)`, ` (3)` … w kolejności malejącej powierzchni.
4. **Dopasowanie tożsamości:** istniejące aktywne strefy `source='auto'` danej
   technologii vs nowe komponenty, po największej powierzchni przecięcia
   (`ST_Area(ST_Intersection)`), przydział zachłanny malejąco po przecięciu:
   - dopasowana para → strefa aktualizuje `polygon` i `name`
     (`custom_name` nietknięte);
   - stara strefa bez komponentu (obszar zniknął albo złączył się z większym)
     → `deleted_at = now()`;
   - komponent bez strefy (nowy obszar albo wynik podziału) → nowy rekord
     (`source='auto'`, `created_by=NULL`).

   Skutki: przy złączeniu dwóch obszarów przeżywa strefa o większym
   przecięciu (jej `custom_name` zostaje), druga znika; przy podziale
   największy kawałek dziedziczy ID i nazwę własną, reszta dostaje świeże
   rekordy z nazwami generowanymi.
5. `ZoneOffering` per strefa: `status='available'`, prędkości = `MAX` po
   adresach **wewnątrz komponentu** (nie po całej technologii jak dotąd).
6. Ukrywanie przez `deleted_at` + wskrzeszanie na rebuildzie: bez zmian,
   per strefa.

Triggery rebuildu bez zmian (offering CRUD, bulk execute/rollback,
import-gis, CLI `rebuild-zones`).

### Skala

Komponentów będzie kilkadziesiąt maksymalnie (miejscowości w rejonie);
dopasowanie par to iloczyn rzędu dziesiątek × dziesiątek — bez optymalizacji.

## Etap 3 — mapa LMS: filtry i panel obszaru (plugin)

Moduł `etacoveragemap`:

- **Filtry nad mapą:** technologia (lista z `/admin/technologies`), źródło
  strefy (auto / ręczne / wszystkie), pokaż-ukryj punkty adresowe. Filtrowanie
  po `properties` GeoJSON po stronie JS.
- **Klik w strefę auto:** panel boczny — nazwa efektywna (z możliwością
  zmiany `custom_name` → `PATCH /admin/zones/{id}`), technologia, licznik
  adresów (`address_count` z `?expand=detail`), lista adresów
  (`/admin/zones/{id}/addresses`, kolumna `has_override`), link per adres do
  `?m=etacoverageaddress`.

## Etap 4 — mapa LMS: edycja pokrycia rysowaniem (plugin)

Leaflet.draw (asset w pluginie) + istniejące API — **bez nowych endpointów**:

1. Użytkownik rysuje polygon/prostokąt (lub startuje z obrysu istniejącej
   auto-zony jako podkładu).
2. Wybór operacji: dodaj ofertę / zmień status / usuń ofertę; technologia,
   status, prędkości, `status_since`, `planned_until`.
3. `POST /admin/map/in-polygon` → lista `rc_codes`.
4. `POST /admin/bulk/preview` z filtrem `rc_codes` → tabela podglądu
   (`affected_count`, próbka adresów, stan obecny → nowy).
5. Potwierdzenie → `POST /admin/bulk/execute` (audit log i rollback per
   operacja już istnieją w API).
6. Po execute odśwież GeoJSON (rebuild auto-zon idzie w `BackgroundTasks` —
   refetch po ~2 s + przycisk ręcznego odświeżenia).
7. Panel „Ostatnie operacje" pod mapą: lista z `GET /admin/bulk-operations`
   (operacja, autor, liczba adresów, data) z przyciskiem rollback przy
   operacjach jeszcze niewycofanych.

Uprawnienia: edycja za `eta_coverage_*` jak w `etacoverageaddress`;
podgląd mapy bez zmian.

## Etap 5 — higiena długoterminowa (API + plugin stats)

- `import-gis --mode diff`: poza dodawaniem nowych ofert raportuje
  **osierocone** — adresy z ofertą technologii, które po bieżącym shapefile
  są dalej niż `--distance` od sieci. Raport (lista rc_code + adres), bez
  automatycznego kasowania; opcjonalna flaga `--remove-orphans` wykonująca
  usunięcie jako operację bulk (z rollbackiem).
- Raport „planned po terminie": rozszerzenie `/admin/coverage/stats` o licznik
  i listę ofert `status='planned'` z `planned_until < today`; wyświetlenie w
  `etacoveragestats`. Tylko raport — zmiana statusu to decyzja człowieka
  (bulkiem albo per adres).

## Poza zakresem

- Automatyczne wygaszanie/awansowanie ofert `planned` po terminie.
- UI zarządzania strefami ręcznymi.
- Zmiany w publicznym schemacie odpowiedzi availability (kontrakt bez zmian —
  zmienia się tylko źródło danych).

## Testy

API (integracyjne, wzorzec istniejących testów rebuildu):

1. Availability nie uwzględnia żadnych stref (adres w polygonie auto-zony bez
   własnej oferty → technologia nieobecna w wyniku).
2. Rebuild tworzy osobne strefy per komponent; nazwy z dominującej
   miejscowości; kolizja nazw → sufiksy.
3. Złączenie obszarów: przeżywa strefa o większym przecięciu, `custom_name`
   zachowane, druga dostaje `deleted_at`.
4. Podział obszaru: największy komponent dziedziczy ID, reszta to nowe strefy.
5. `custom_name` przeżywa zwykły rebuild; `PATCH` polygonu auto-zony → 422,
   `PATCH custom_name` → 200.
6. Prędkości `ZoneOffering` = MAX per komponent, nie globalnie.
7. `import-gis --mode diff` raportuje osierocone oferty; `--remove-orphans`
   tworzy operację bulk z rollbackiem.

Plugin: testy ręczne UI (filtry, panel strefy, pełny przebieg rysowanie →
preview → execute → rollback).

## Kolejność wdrożenia

Etap 1 → 2 → 3 → 4 → 5. Etap 1 jest samodzielny i naprawia realny błąd
sprzedażowy — wdrożyć od razu, niezależnie od reszty.
