# Techninė užduotis: ISP adresų ir paslaugų prieinamumo sistema

**Užsakovas:** Etanetas (ISP, Šalčininkai)
**Dokumento versija:** 1.0
**Data:** 2026-05-15
**Statusas:** MVP specifikacija, paruošta įgyvendinimui

---

## Turinys

1. [Tikslas ir kontekstas](#1-tikslas-ir-kontekstas)
2. [Technologinis stack'as](#2-technologinis-stackas)
3. [Duomenų modelis](#3-duomenų-modelis)
4. [SQL migracija](#4-sql-migracija)
5. [Užklausų logika](#5-užklausų-logika)
6. [API endpoint'ai](#6-api-endpointai)
7. [Autentifikacija ir autorizacija](#7-autentifikacija-ir-autorizacija)
8. [LMS Plus plugin'as (darbuotojų sąsaja)](#8-lms-plus-pluginas-darbuotojų-sąsaja)
9. [Klientų paieška etanetas.lt](#9-klientų-paieška-etanetaslt)
10. [Duomenų importas iš RC](#10-duomenų-importas-iš-rc)
11. [Saugumas ir audit'as](#11-saugumas-ir-auditas)
12. [Etapai ir terminai](#12-etapai-ir-terminai)
13. [Atviri klausimai](#13-atviri-klausimai)

---

## 1. Tikslas ir kontekstas

### 1.1. Verslo problema

Etanetas teikia interneto paslaugas Šalčininkų ir Vilniaus rajonuose. Šiuo metu nėra centralizuotos sistemos, leidžiančios:

- Klientui pačiam patikrinti, kokios paslaugos prieinamos jo adresu
- Pardavimų ir techniniam personalui greitai atsakyti į užklausas „ar galim prijungti X gatvėje"
- Sistemingai planuoti tinklo plėtrą pagal padengimo žemėlapį
- Saugoti adresų lygmens technologinį žemėlapį (kur yra šviesolaidis, kur tik bevielis, kur planuojama)

### 1.2. Sprendimas

Sukurti sistemą, kurią sudaro:

1. **Duomenų bazė** su visais Lietuvos adresais (importuotais iš Registrų centro atvirųjų duomenų)
2. **Public API** klientų paieškai (be autentifikacijos)
3. **Admin API** darbuotojų valdymui (su autentifikacija)
4. **Paieškos modulis** klientams etanetas.lt tinklapyje
5. **LMS Plus plugin'as** darbuotojams (paslaugų pririšimas, grupinės operacijos, vartotojų valdymas)

### 1.3. MVP apimtis

| Aspektas | Apimtis |
|---|---|
| Geografiškai (duomenys) | Visa Lietuva (~2.1 mln. adresų) |
| Geografiškai (naudojimas) | Šalčininkų + Vilniaus raj. |
| Funkcionalumas | Pilnas (admin + API + klientų paieška) |
| Implementatorius | Vidinė komanda |
| Integracija su LMS | LMS Plus plugin'as — darbuotojų sąsaja |
| Žemėlapio UI | Atidedamas (be jo MVP'e) |

### 1.4. Ateities planas

- SSO autentifikacija (vietoj atskirų API key'ų)
- LMS klientų užsakymų automatizavimas (per tinklapį → LMS sutarties juodraštis)
- Žemėlapio UI zonų piešimui
- Plėtra į kitus regionus

---

## 2. Technologinis stack'as

| Sluoksnis | Pasirinkimas | Argumentacija |
|---|---|---|
| Duomenų bazė | PostgreSQL 16 + PostGIS 3.4 | Geo užklausų standartas, brandus, nemokama |
| Backend kalba | Python 3.12 | Komanda jau moka, geo ekosistema (geopandas, shapely) |
| API framework | FastAPI | Modernus, asinchroninis, automatinė OpenAPI dokumentacija |
| ORM | SQLAlchemy 2.x + GeoAlchemy2 | Standartas Python ekosistemoje, palaiko PostGIS |
| Slaptažodžiai/key hash | bcrypt | Industrinis standartas |
| ETL (RC importas) | Python + spinta SDK | Oficialus data.gov.lt klientas |
| Migracijos | Alembic | SQLAlchemy ekosistema |
| Testavimas | pytest + httpx | Standartas |
| Konteinerizavimas | Docker + docker-compose | Lengva paleisti vystymo ir produkcijos aplinkose |

**Kodėl ne Go/Rust:** API užklausų greitis priklauso nuo DB užklausos, ne kalbos. Su PostgreSQL connection pool kakliuku visos kalbos suvienodėja. Python privalumai (komanda moka, geo ekosistema, greitas development) nusveria mažą runtime persvarą.

**Kodėl Python backend'e, ne PHP:** Nors plugin'as bus PHP (LMS hook'ų sistema diktuoja), pati backend logika lieka Python sluoksnyje. Argumentai: (1) Python geo ekosistema (geopandas, shapely, spinta SDK RC duomenims) — PHP atitikmenų nėra arba jie silpnesni; (2) atskiras backend leis ateityje pridėti kitas integracijas (mobili app, kitos sistemos) nepriklausomai nuo LMS; (3) PostgreSQL/PostGIS Python pusėje natūralu; (4) LMS plugin'as tampa „plonas klientas" — tik UI ir HTTP kvietimai.

---

## 3. Duomenų modelis

Sistema sudaryta iš 13 lentelių, suskirstytų į 4 logines grupes.

### 3.1. Grupė A: Adresų hierarchija (iš Registrų centro)

Read-only duomenys, sinchronizuojami iš RC. Atspindi RC oficialią hierarchiją.

#### `counties` — apskritys

| Laukas | Tipas | Aprašymas |
|---|---|---|
| `rc_code` | INT, PK | RC apskrities kodas |
| `name` | TEXT | Pavadinimas, pvz. „Vilniaus apskritis" |
| `synced_at` | TIMESTAMP | Paskutinis sync iš RC |

#### `municipalities` — savivaldybės

| Laukas | Tipas | Aprašymas |
|---|---|---|
| `rc_code` | INT, PK | RC savivaldybės kodas |
| `county_code` | INT, FK | → counties.rc_code |
| `name` | TEXT | „Šalčininkų rajono savivaldybė" |
| `type` | TEXT | rajono / miesto |
| `synced_at` | TIMESTAMP | |

#### `localities` — gyvenvietės

| Laukas | Tipas | Aprašymas |
|---|---|---|
| `rc_code` | INT, PK | RC gyvenvietės kodas |
| `muni_code` | INT, FK | → municipalities.rc_code |
| `name` | TEXT | „Šalčininkai", „Eišiškės" |
| `type` | TEXT | miestas / miestelis / kaimas / vienkiemis |
| `boundary` | GEOMETRY(MULTIPOLYGON, 4326) | Gyvenvietės ribos |
| `synced_at` | TIMESTAMP | |

#### `streets` — gatvės

| Laukas | Tipas | Aprašymas |
|---|---|---|
| `rc_code` | INT, PK | RC gatvės kodas |
| `locality_code` | INT, FK | → localities.rc_code |
| `name` | TEXT | „Vilniaus g." |
| `full_name` | TEXT | „Vilniaus g., Šalčininkai" (search optimizuotas) |
| `axis` | GEOMETRY(MULTILINESTRING, 4326) | Gatvės ašinė linija |
| `synced_at` | TIMESTAMP | |

#### `addresses` — adresai

| Laukas | Tipas | Aprašymas |
|---|---|---|
| `rc_code` | BIGINT, PK | RC adreso kodas |
| `street_code` | INT, FK, nullable | → streets.rc_code (NULL kaimuose be gatvių) |
| `locality_code` | INT, FK | → localities.rc_code |
| `house_no` | TEXT | „12", „14A", „99" |
| `postal_code` | TEXT | „17112" |
| `point` | GEOMETRY(POINT, 4326) | Tikslios koordinatės |
| `synced_at` | TIMESTAMP | |
| `deleted_at` | TIMESTAMP, nullable | Jei adresas išregistruotas RC, žymimas (ne trinamas fiziškai) |

### 3.2. Grupė B: Technologijų katalogas

#### `technology_types` — pirminiai tipai

Klientui rodomi technologijos tipai. Atskirti nuo variantų, kad būtų lengva pervadinti.

| Laukas | Tipas | Aprašymas |
|---|---|---|
| `id` | UUID, PK | |
| `code` | TEXT, UNIQUE | FIBER, ETHERNET, WIRELESS, LTE |
| `display_name` | TEXT | Plugin'e: „Šviesolaidis" |
| `public_name` | TEXT | Klientui: „Šviesolaidis" |
| `sort_order` | INT | UI tvarkai |
| `active` | BOOL | |

**Pradiniai duomenys:**

| code | display_name | public_name | sort_order |
|---|---|---|---|
| FIBER | Šviesolaidis | Šviesolaidis | 10 |
| ETHERNET | Ethernet | Ethernet | 20 |
| WIRELESS | Bevielis | Bevielis | 30 |
| LTE | LTE | Mobilus internetas | 40 |

#### `technologies` — konkretūs variantai

| Laukas | Tipas | Aprašymas |
|---|---|---|
| `id` | UUID, PK | |
| `type_id` | UUID, FK | → technology_types.id |
| `variant_code` | TEXT, UNIQUE | gpon, xgpon, fttb_utp, p2mp_5ghz, p2p_5ghz, 4g_lte, 5g_nr |
| `display_name` | TEXT | „Šviesolaidis GPON", „Šviesolaidis XGPON" |
| `theoretical_max_dl_mbps` | INT | Techniniai maksimumai (informaciniai) |
| `theoretical_max_ul_mbps` | INT | |
| `sort_order` | INT | |
| `active` | BOOL | |

**Pradiniai duomenys:**

| type | variant | display_name | max_dl | max_ul |
|---|---|---|---|---|
| FIBER | gpon | Šviesolaidis GPON | 2500 | 1250 |
| FIBER | xgpon | Šviesolaidis XGPON | 10000 | 10000 |
| ETHERNET | fttb_utp | Ethernet (FTTB) | 1000 | 1000 |
| WIRELESS | p2mp_5ghz | Bevielis 5GHz P2MP | 200 | 100 |
| WIRELESS | p2p_5ghz | Bevielis 5GHz P2P | 500 | 250 |
| LTE | 4g_lte | LTE 4G | 150 | 50 |
| LTE | 5g_nr | LTE 5G | 1000 | 100 |

### 3.3. Grupė C: Paslaugų prieinamumas

#### `service_zones` — zonos žemėlapyje

| Laukas | Tipas | Aprašymas |
|---|---|---|
| `id` | UUID, PK | |
| `name` | TEXT | „Šalčininkai-centras", „Eišiškių šiaurinė" |
| `description` | TEXT, nullable | |
| `polygon` | GEOMETRY(MULTIPOLYGON, 4326), nullable | Geometrija (MVP'e gali būti NULL — zona kuriama per gatvių sąrašą) |
| `priority` | INT | Kai adresas patenka į kelias zonas — laimi su didžiausiu priority |
| `created_at` | TIMESTAMP | |
| `created_by` | UUID, FK | → users.id |

MVP'e be žemėlapio UI zonos kuriamos kitaip: arba per gatvių/gyvenviečių sąrašą, arba pateikiant koordinačių porą. Sistema sukuria poligoną (`ST_ConvexHull` ar `ST_Buffer`) automatiškai.

#### `zone_offerings` — kas prieinama zonoje

| Laukas | Tipas | Aprašymas |
|---|---|---|
| `id` | UUID, PK | |
| `zone_id` | UUID, FK | → service_zones.id |
| `technology_id` | UUID, FK | → technologies.id |
| `status` | TEXT | available / planned / under_construction / unavailable |
| `max_download_mbps` | INT | Realus greitis šitoje zonoje |
| `max_upload_mbps` | INT | |
| `status_since` | DATE | Kada šis statusas tapo aktualus |
| `planned_until` | DATE, nullable | Kada planuojama prijungti (jei status = planned) |
| `notes` | TEXT, nullable | |
| `created_at` | TIMESTAMP | |
| `updated_at` | TIMESTAMP | |

UNIQUE (`zone_id`, `technology_id`).

#### `address_offerings` — išimtys konkretiems adresams

| Laukas | Tipas | Aprašymas |
|---|---|---|
| `id` | UUID, PK | |
| `address_code` | BIGINT, FK | → addresses.rc_code |
| `technology_id` | UUID, FK | → technologies.id |
| `status` | TEXT | available / planned / under_construction / unavailable |
| `max_download_mbps` | INT | |
| `max_upload_mbps` | INT | |
| `status_since` | DATE | |
| `planned_until` | DATE, nullable | |
| `notes` | TEXT, nullable | |
| `created_by` | UUID, FK | → users.id |
| `bulk_operation_id` | UUID, FK, nullable | → bulk_operations.id |
| `created_at` | TIMESTAMP | |
| `updated_at` | TIMESTAMP | |

UNIQUE (`address_code`, `technology_id`).

### 3.4. Grupė D: Administravimas

#### `users` — vartotojai

| Laukas | Tipas | Aprašymas |
|---|---|---|
| `id` | UUID, PK | |
| `username` | TEXT, UNIQUE | |
| `email` | TEXT, UNIQUE | |
| `role` | TEXT | admin / editor / viewer |
| `active` | BOOL | |
| `created_at` | TIMESTAMP | |

Slaptažodžių lauką MVP'e palikti tuščią — autentifikacija per API key, ne password. SSO ateityje pridės savo identifikaciją.

#### `api_keys` — API raktai

| Laukas | Tipas | Aprašymas |
|---|---|---|
| `id` | UUID, PK | |
| `user_id` | UUID, FK | → users.id |
| `key_hash` | TEXT | bcrypt hash, originalas niekur nesaugomas |
| `name` | TEXT | „Mario laptop", „LMS plugin" |
| `last_used_at` | TIMESTAMP, nullable | |
| `expires_at` | TIMESTAMP, nullable | NULL = neribota |
| `created_at` | TIMESTAMP | |
| `revoked_at` | TIMESTAMP, nullable | |

#### `bulk_operations` — grupinių operacijų istorija

| Laukas | Tipas | Aprašymas |
|---|---|---|
| `id` | UUID, PK | |
| `user_id` | UUID, FK | → users.id |
| `operation_type` | TEXT | add_offering / update_status / update_planned_until / remove_offering |
| `filter_criteria` | JSONB | Paieška, kuri buvo naudota |
| `affected_count` | INT | Kiek įrašų buvo paveikta |
| `rollback_data` | JSONB | Senos reikšmės kiekvienam pakeistam įrašui |
| `created_at` | TIMESTAMP | |
| `rolled_back_at` | TIMESTAMP, nullable | |

#### `audit_log` — visi pakeitimai

| Laukas | Tipas | Aprašymas |
|---|---|---|
| `id` | BIGSERIAL, PK | |
| `user_id` | UUID, FK | → users.id |
| `entity_type` | TEXT | address_offering / zone_offering / service_zone / technology / user |
| `entity_id` | TEXT | Pakeisto įrašo ID |
| `action` | TEXT | create / update / delete |
| `diff` | JSONB | Pakeitimai (prieš / po) |
| `at` | TIMESTAMP | |

Užpildoma automatiškai per SQLAlchemy event hook'us arba PostgreSQL trigger'ius.


---

## 4. SQL migracija

Pradinė schema sukuriama per Alembic migraciją. Pateikiamas pilnas paleidžiamas `.sql` failas projekto `/migrations/001_initial.sql`.

### 4.1. Plėtinių aktyvavimas

```sql
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
```

### 4.2. Adresų hierarchija

```sql
CREATE TABLE counties (
    rc_code       INT PRIMARY KEY,
    name          TEXT NOT NULL,
    synced_at     TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE municipalities (
    rc_code       INT PRIMARY KEY,
    county_code   INT NOT NULL REFERENCES counties(rc_code),
    name          TEXT NOT NULL,
    type          TEXT NOT NULL,
    synced_at     TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_municipalities_county ON municipalities(county_code);

CREATE TABLE localities (
    rc_code       INT PRIMARY KEY,
    muni_code     INT NOT NULL REFERENCES municipalities(rc_code),
    name          TEXT NOT NULL,
    type          TEXT NOT NULL,
    boundary      GEOMETRY(MULTIPOLYGON, 4326),
    synced_at     TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_localities_muni ON localities(muni_code);
CREATE INDEX idx_localities_boundary ON localities USING GIST(boundary);
CREATE INDEX idx_localities_name_trgm ON localities USING GIN(name gin_trgm_ops);

CREATE TABLE streets (
    rc_code       INT PRIMARY KEY,
    locality_code INT NOT NULL REFERENCES localities(rc_code),
    name          TEXT NOT NULL,
    full_name     TEXT NOT NULL,
    axis          GEOMETRY(MULTILINESTRING, 4326),
    synced_at     TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_streets_locality ON streets(locality_code);
CREATE INDEX idx_streets_full_name_trgm ON streets USING GIN(full_name gin_trgm_ops);

CREATE TABLE addresses (
    rc_code       BIGINT PRIMARY KEY,
    street_code   INT REFERENCES streets(rc_code),
    locality_code INT NOT NULL REFERENCES localities(rc_code),
    house_no      TEXT NOT NULL,
    postal_code   TEXT,
    point         GEOMETRY(POINT, 4326),
    synced_at     TIMESTAMP NOT NULL DEFAULT NOW(),
    deleted_at    TIMESTAMP
);
CREATE INDEX idx_addresses_street ON addresses(street_code) WHERE deleted_at IS NULL;
CREATE INDEX idx_addresses_locality ON addresses(locality_code) WHERE deleted_at IS NULL;
CREATE INDEX idx_addresses_point ON addresses USING GIST(point);
CREATE INDEX idx_addresses_house_no_trgm ON addresses USING GIN(house_no gin_trgm_ops);
```

### 4.3. Technologijos

```sql
CREATE TABLE technology_types (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    code          TEXT UNIQUE NOT NULL,
    display_name  TEXT NOT NULL,
    public_name   TEXT NOT NULL,
    sort_order    INT NOT NULL DEFAULT 100,
    active        BOOL NOT NULL DEFAULT TRUE
);

CREATE TABLE technologies (
    id                          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    type_id                     UUID NOT NULL REFERENCES technology_types(id),
    variant_code                TEXT UNIQUE NOT NULL,
    display_name                TEXT NOT NULL,
    theoretical_max_dl_mbps     INT,
    theoretical_max_ul_mbps     INT,
    sort_order                  INT NOT NULL DEFAULT 100,
    active                      BOOL NOT NULL DEFAULT TRUE
);
CREATE INDEX idx_technologies_type ON technologies(type_id);
```

### 4.4. Paslaugų prieinamumas

```sql
CREATE TABLE service_zones (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name          TEXT NOT NULL,
    description   TEXT,
    polygon       GEOMETRY(MULTIPOLYGON, 4326),
    priority      INT NOT NULL DEFAULT 100,
    created_at    TIMESTAMP NOT NULL DEFAULT NOW(),
    created_by    UUID REFERENCES users(id)
);
CREATE INDEX idx_service_zones_polygon ON service_zones USING GIST(polygon);

CREATE TABLE zone_offerings (
    id                   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    zone_id              UUID NOT NULL REFERENCES service_zones(id) ON DELETE CASCADE,
    technology_id        UUID NOT NULL REFERENCES technologies(id),
    status               TEXT NOT NULL CHECK (status IN ('available', 'planned', 'under_construction', 'unavailable')),
    max_download_mbps    INT,
    max_upload_mbps      INT,
    status_since         DATE NOT NULL DEFAULT CURRENT_DATE,
    planned_until        DATE,
    notes                TEXT,
    created_at           TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (zone_id, technology_id)
);
CREATE INDEX idx_zone_offerings_zone ON zone_offerings(zone_id);
CREATE INDEX idx_zone_offerings_tech ON zone_offerings(technology_id);
CREATE INDEX idx_zone_offerings_status ON zone_offerings(status);

CREATE TABLE address_offerings (
    id                   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    address_code         BIGINT NOT NULL REFERENCES addresses(rc_code),
    technology_id        UUID NOT NULL REFERENCES technologies(id),
    status               TEXT NOT NULL CHECK (status IN ('available', 'planned', 'under_construction', 'unavailable')),
    max_download_mbps    INT,
    max_upload_mbps      INT,
    status_since         DATE NOT NULL DEFAULT CURRENT_DATE,
    planned_until        DATE,
    notes                TEXT,
    created_by           UUID REFERENCES users(id),
    bulk_operation_id    UUID,
    created_at           TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (address_code, technology_id)
);
CREATE INDEX idx_address_offerings_addr ON address_offerings(address_code);
CREATE INDEX idx_address_offerings_tech ON address_offerings(technology_id);
CREATE INDEX idx_address_offerings_status ON address_offerings(status);
CREATE INDEX idx_address_offerings_bulk ON address_offerings(bulk_operation_id);
```

### 4.5. Administravimas

```sql
CREATE TABLE users (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    username      TEXT UNIQUE NOT NULL,
    email         TEXT UNIQUE NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('admin', 'editor', 'viewer')),
    active        BOOL NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE api_keys (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key_hash      TEXT NOT NULL,
    name          TEXT NOT NULL,
    last_used_at  TIMESTAMP,
    expires_at    TIMESTAMP,
    created_at    TIMESTAMP NOT NULL DEFAULT NOW(),
    revoked_at    TIMESTAMP
);
CREATE INDEX idx_api_keys_user ON api_keys(user_id) WHERE revoked_at IS NULL;

CREATE TABLE bulk_operations (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id           UUID NOT NULL REFERENCES users(id),
    operation_type    TEXT NOT NULL,
    filter_criteria   JSONB NOT NULL,
    affected_count    INT NOT NULL,
    rollback_data     JSONB,
    created_at        TIMESTAMP NOT NULL DEFAULT NOW(),
    rolled_back_at    TIMESTAMP
);
CREATE INDEX idx_bulk_operations_user ON bulk_operations(user_id);
CREATE INDEX idx_bulk_operations_created ON bulk_operations(created_at DESC);

CREATE TABLE audit_log (
    id            BIGSERIAL PRIMARY KEY,
    user_id       UUID REFERENCES users(id),
    entity_type   TEXT NOT NULL,
    entity_id     TEXT NOT NULL,
    action        TEXT NOT NULL,
    diff          JSONB,
    at            TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_audit_log_entity ON audit_log(entity_type, entity_id);
CREATE INDEX idx_audit_log_user ON audit_log(user_id);
CREATE INDEX idx_audit_log_at ON audit_log(at DESC);

ALTER TABLE address_offerings
    ADD CONSTRAINT fk_address_offerings_bulk
    FOREIGN KEY (bulk_operation_id) REFERENCES bulk_operations(id);
```

### 4.6. Pradiniai duomenys

```sql
-- Technologijų tipai
INSERT INTO technology_types (code, display_name, public_name, sort_order) VALUES
    ('FIBER',    'Šviesolaidis',         'Šviesolaidis',          10),
    ('ETHERNET', 'Ethernet',             'Ethernet',              20),
    ('WIRELESS', 'Bevielis',             'Bevielis',              30),
    ('LTE',      'LTE',                  'Mobilus internetas',    40);

-- Technologijų variantai
INSERT INTO technologies (type_id, variant_code, display_name, theoretical_max_dl_mbps, theoretical_max_ul_mbps, sort_order) VALUES
    ((SELECT id FROM technology_types WHERE code='FIBER'),    'gpon',       'Šviesolaidis GPON',    2500,  1250, 10),
    ((SELECT id FROM technology_types WHERE code='FIBER'),    'xgpon',      'Šviesolaidis XGPON',  10000, 10000, 11),
    ((SELECT id FROM technology_types WHERE code='ETHERNET'), 'fttb_utp',   'Ethernet (FTTB)',      1000,  1000, 20),
    ((SELECT id FROM technology_types WHERE code='WIRELESS'), 'p2mp_5ghz',  'Bevielis 5GHz P2MP',    200,   100, 30),
    ((SELECT id FROM technology_types WHERE code='WIRELESS'), 'p2p_5ghz',   'Bevielis 5GHz P2P',     500,   250, 31),
    ((SELECT id FROM technology_types WHERE code='LTE'),      '4g_lte',     'LTE 4G',                150,    50, 40),
    ((SELECT id FROM technology_types WHERE code='LTE'),      '5g_nr',      'LTE 5G',               1000,   100, 41);
```

Pirmojo super-admin vartotojo sukūrimas — per CLI komandą:

```bash
python -m app.cli create-admin --username jonas --email jonas@etanetas.lt
# Sugeneruoja inicialų API key, parodo terminale (matomas TIK VIENĄ KARTĄ)
```

---

## 5. Užklausų logika

### 5.1. Pagrindinė klausimo užklausa

„Kas prieinama adresui X?" — pati svarbiausia užklausa sistemoje. Atsakymas surenkamas iš dviejų šaltinių su prioritetu.

```sql
WITH addr AS (
    SELECT rc_code, point FROM addresses WHERE rc_code = $1
),
-- 1) Konkretūs adresų įrašai (visada laimi)
addr_offerings AS (
    SELECT
        ao.technology_id,
        ao.status,
        ao.max_download_mbps,
        ao.max_upload_mbps,
        ao.status_since,
        ao.planned_until,
        'address' AS source
    FROM address_offerings ao
    WHERE ao.address_code = $1
),
-- 2) Zonų įrašai (tik tie technology_id, kurių NĖRA addr_offerings)
zone_offerings_filtered AS (
    SELECT DISTINCT ON (zo.technology_id)
        zo.technology_id,
        zo.status,
        zo.max_download_mbps,
        zo.max_upload_mbps,
        zo.status_since,
        zo.planned_until,
        'zone' AS source
    FROM zone_offerings zo
    JOIN service_zones sz ON sz.id = zo.zone_id
    JOIN addr a ON ST_Contains(sz.polygon, a.point)
    WHERE zo.technology_id NOT IN (SELECT technology_id FROM addr_offerings)
    ORDER BY zo.technology_id, sz.priority DESC
)
SELECT
    tt.public_name AS technology,
    MAX(combined.max_download_mbps) AS max_dl_mbps,
    MAX(combined.max_upload_mbps) AS max_ul_mbps,
    combined.status,
    MIN(combined.planned_until) AS planned_until
FROM (
    SELECT * FROM addr_offerings
    UNION ALL
    SELECT * FROM zone_offerings_filtered
) combined
JOIN technologies t ON t.id = combined.technology_id
JOIN technology_types tt ON tt.id = t.type_id
WHERE combined.status IN ('available', 'planned')
  AND tt.active = TRUE
  AND t.active = TRUE
GROUP BY tt.id, tt.public_name, tt.sort_order, combined.status
ORDER BY tt.sort_order;
```

**Svarbu:**
- Konkretus įrašas adresui **visada nugali** zonos įrašą (sumažinta priority logika)
- Jei adresas patenka į kelias zonas, laimi su didžiausiu `priority`
- Klientui rodom `available` ir `planned`, slepiame `unavailable` ir `under_construction`
- Grupuojam pagal `public_name` — XGPON ir GPON susilieja į vieną „Šviesolaidis" eilutę su didžiausiu greičiu

### 5.2. Autocomplete paieška

```sql
SELECT a.rc_code,
       s.name || ' ' || a.house_no || ', ' || l.name AS full_address,
       a.postal_code
FROM addresses a
JOIN streets s ON s.rc_code = a.street_code
JOIN localities l ON l.rc_code = a.locality_code
WHERE a.deleted_at IS NULL
  AND (
      s.full_name % $1
      OR l.name % $1
      OR (s.name || ' ' || a.house_no || ', ' || l.name) % $1
  )
ORDER BY similarity(s.full_name || ' ' || a.house_no, $1) DESC
LIMIT 10;
```

`%` operatorius su pg_trgm — tolerantiškas rašybos klaidoms ir lietuviškų rašmenų variacijoms.


---

## 6. API endpoint'ai

Sistemoje du atskiri API sluoksniai su skirtingais saugumo lygiais.

### 6.1. Public API (be autentifikacijos)

Skirtas etanetas.lt tinklapio klientų paieškai.

| Method | Endpoint | Aprašymas |
|---|---|---|
| GET | `/api/v1/public/addresses/search?q=...` | Autocomplete (max 10 rezultatų) |
| GET | `/api/v1/public/addresses/{rc_code}/availability` | Prieinamumas konkretiam adresui |

**Apsauga:**
- Rate limiting: 60 užklausų/min iš vieno IP (per `slowapi` middleware)
- CORS: tik etanetas.lt domenas
- HTTPS privaloma

**Atsakymo pavyzdys `/availability`:**

```json
{
  "address": {
    "rc_code": 12345678,
    "full_address": "Vilniaus g. 12, Šalčininkai",
    "postal_code": "17112"
  },
  "available": [
    {
      "technology": "Šviesolaidis",
      "max_dl_mbps": 2000,
      "max_ul_mbps": 1000
    },
    {
      "technology": "Bevielis",
      "max_dl_mbps": 100,
      "max_ul_mbps": 30
    }
  ],
  "planned": [
    {
      "technology": "Ethernet",
      "planned_until": "2026-09-01"
    }
  ]
}
```

`technology_variant` (GPON, XGPON, ir t.t.) neeksponuojamas klientui.

### 6.2. Internal API (su API key)

Visi admin endpoint'ai. Reikalauja `X-API-Key` header'į.

**Adresų paieška ir info:**

| Method | Endpoint | Rolė |
|---|---|---|
| POST | `/api/v1/admin/addresses/search` | viewer+ |
| GET | `/api/v1/admin/addresses/{rc_code}` | viewer+ |

**Technologijų katalogas:**

| Method | Endpoint | Rolė |
|---|---|---|
| GET | `/api/v1/admin/technology-types` | viewer+ |
| GET | `/api/v1/admin/technologies` | viewer+ |
| POST/PUT/DELETE | `/api/v1/admin/technologies` | admin |
| PUT | `/api/v1/admin/technology-types/{id}` | admin |

**Zonos:**

| Method | Endpoint | Rolė |
|---|---|---|
| GET | `/api/v1/admin/zones` | viewer+ |
| POST | `/api/v1/admin/zones` | editor+ |
| PUT | `/api/v1/admin/zones/{id}` | editor+ |
| DELETE | `/api/v1/admin/zones/{id}` | admin |
| GET | `/api/v1/admin/zones/{id}/offerings` | viewer+ |
| POST | `/api/v1/admin/zones/{id}/offerings` | editor+ |

**Adresų paslaugos:**

| Method | Endpoint | Rolė |
|---|---|---|
| GET | `/api/v1/admin/addresses/{rc_code}/offerings` | viewer+ |
| POST | `/api/v1/admin/addresses/{rc_code}/offerings` | editor+ |
| PUT | `/api/v1/admin/address-offerings/{id}` | editor+ |
| DELETE | `/api/v1/admin/address-offerings/{id}` | editor+ |

**Grupinės operacijos:**

| Method | Endpoint | Rolė |
|---|---|---|
| POST | `/api/v1/admin/bulk/preview` | editor+ |
| POST | `/api/v1/admin/bulk/execute` | editor+ |
| POST | `/api/v1/admin/bulk/{id}/rollback` | editor+ (per 15 min) / admin (visada) |

**Audit ir istorija:**

| Method | Endpoint | Rolė |
|---|---|---|
| GET | `/api/v1/admin/audit-log` | admin |
| GET | `/api/v1/admin/bulk-operations` | viewer+ |
| GET | `/api/v1/admin/addresses/{rc_code}/history` | viewer+ |

**Vartotojų valdymas:**

| Method | Endpoint | Rolė |
|---|---|---|
| GET | `/api/v1/admin/users` | admin |
| POST | `/api/v1/admin/users` | admin |
| PUT | `/api/v1/admin/users/{id}` | admin |
| DELETE | `/api/v1/admin/users/{id}` | admin |
| POST | `/api/v1/admin/users/{id}/api-keys` | admin |
| GET | `/api/v1/admin/users/{id}/api-keys` | admin |
| DELETE | `/api/v1/admin/api-keys/{id}` | admin |

### 6.3. Bulk operacijų semantika

**Preview** užklausa:

```json
POST /api/v1/admin/bulk/preview
{
  "operation": {
    "type": "add_offering",
    "technology_id": "...",
    "status": "available",
    "max_dl_mbps": 1000,
    "max_ul_mbps": 500,
    "status_since": "2026-05-15"
  },
  "filter": {
    "locality_code": 12345,
    "street_codes": [101, 102, 103],
    "house_no_pattern": null
  }
}
```

Atsakymas:

```json
{
  "affected_count": 47,
  "sample": [
    {"address": "Vilniaus g. 12, Šalčininkai", "current": null, "new": {...}},
    {"address": "Vilniaus g. 14, Šalčininkai", "current": null, "new": {...}}
  ],
  "preview_token": "tmp_xyz123..."
}
```

`preview_token` galioja 5 min — užtikrina, kad `execute` paveiks tik tai, ką vartotojas matė preview lange (apsauga nuo race condition).

**Execute** užklausa naudoja preview_token:

```json
POST /api/v1/admin/bulk/execute
{
  "preview_token": "tmp_xyz123..."
}
```

Saugiklis: vienas vartotojas negali per minutę paveikti daugiau nei 5000 adresų. Daugiau — reikia papildomo admin patvirtinimo.

---

## 7. Autentifikacija ir autorizacija

### 7.1. API key autentifikacija

Visi internal endpoint'ai reikalauja header'į:

```
X-API-Key: etn_pk_3xK9mZQp7vN2bL5wRfH8tY4uA1dE6sC0
```

**Saugumas:**
- API key generuojamas naudojant `secrets.token_urlsafe(32)`
- DB saugomas tik `bcrypt` hash
- Originalas matomas TIK sukūrimo metu (turi būti rodomas vartotojui vieną kartą)
- Prefix `etn_pk_` padeda atpažinti token'ą jei jis netyčia paskelbtas viešai

**Verifikacija:**

```python
async def authenticate(api_key_header: str) -> User:
    # 1. Suskaityti aktyvius api_keys įrašus
    # 2. Kiekvienam — bcrypt.checkpw(api_key_header, key_hash)
    # 3. Match → įdėti user į request context, update last_used_at
    # 4. No match → 401 Unauthorized
```

### 7.2. Rolės ir leidimai

| Rolė | Aprašymas | Galimybės |
|---|---|---|
| `viewer` | Skaitytojas | GET endpoint'ai, paieška, žiūrėjimas |
| `editor` | Redaktorius | + paslaugų pridėjimas/keitimas, grupinės operacijos |
| `admin` | Administratorius | + zonų pašalinimas, vartotojų valdymas, audit log |

Endpoint'as `@require_role('editor')` dekoratorius patikrina `request.user.role`.

### 7.3. SSO ateičiai

Kai bus pridėtas SSO:
- `users.password_hash` lieka NULL — auth per SSO
- Pridedamas `users.external_id` (SSO provider'io vartotojo ID)
- JWT token autentifikacija veikia šalia API key (machine-to-machine integracijoms)
- Schema nereikalauja keisti

---

## 8. LMS Plus plugin'as (darbuotojų sąsaja)

Vietoje atskiros admin panelės — LMS Plus plugin'as. Argumentai:

- Darbuotojai jau dirba LMS'e kasdien — viena sąsaja vietoje dviejų
- LMS turi savo autentifikaciją, sesijų valdymą, vartotojų sąrašą
- Nereikia diegti, hostinti ar palaikyti atskiros aplikacijos
- Plugin'as kviečia mūsų Python API per X-API-Key — visa logika lieka backend'e

### 8.1. Technologinis stack'as

| Sluoksnis | Pasirinkimas | Argumentacija |
|---|---|---|
| Server-side | PHP (LMS plugin API) | Naudoja LMS hook'ų sistemą |
| Frontend interaktyvumas | Alpine.js 3.x | Lengvas (~15 KB), be build'inimo, įrašai į HTML atributus |
| Server interakcijos | HTMX 2.x | AJAX užklausos tiesiai iš HTML, be JSON parser'ių |
| HTTP klientas (PHP) | guzzlehttp/guzzle | PHP standartas |
| API kalbėjimas | X-API-Key header, JSON | Stabili integracija su Python API |
| UI bazė | LMS Smarty template'ai + custom CSS | Vizualiai integruojasi į LMS |
| Build įrankis | **Nereikia** | Alpine + HTMX per CDN arba lokalūs failai |

**Kodėl Alpine + HTMX, ne Vue/React:**

Komanda neturi patirties su moderniais SPA framework'ais. Alpine + HTMX duoda 90% reikalingo funkcionalumo be Vue/React komplikacijos:

- **Mokymosi laikas:** 2-3 dienos vs 2-3 savaitės
- **Build pipeline:** nereikia (Vue/React reikalauja Vite + npm)
- **Embed'inimas LMS:** natūralus — Alpine atributai įrašomi tiesiai į Smarty template'us
- **Debug'as:** atveri DevTools, matai HTML su atributais. Be sourcemap'ų, be virtual DOM
- **Komandos vystymas:** bet kas, kas moka HTML + truputį JS

Migracija ateičiai švari: jei vėliau prireiks sudėtingo UI (pvz., žemėlapio su drag-and-drop), Alpine komponentai veikia šalia Vue/React komponentų toje pačioje aplikacijoje. Galima palaipsniui keisti tik tuos ekranus, kuriems reikia.

**Pavyzdys — adresų lentelė su žymėjimu:**

```html
<div x-data="addressesManager()" x-init="loadAddresses()">
  <table>
    <thead>
      <tr>
        <th><input type="checkbox" @change="selectAll($event.target.checked)"></th>
        <th>Adresas</th>
        <th>Technologija</th>
        <th>Statusas</th>
      </tr>
    </thead>
    <tbody>
      <template x-for="addr in addresses" :key="addr.rc_code">
        <tr>
          <td><input type="checkbox" :value="addr.rc_code" x-model="selected"></td>
          <td x-text="addr.full_address"></td>
          <td x-text="addr.technology"></td>
          <td x-text="addr.status"></td>
        </tr>
      </template>
    </tbody>
  </table>

  <div x-show="selected.length > 0" class="toolbar">
    Pažymėta: <span x-text="selected.length"></span>
    <button @click="openBulkDialog()">Grupinė operacija</button>
  </div>
</div>

<script>
function addressesManager() {
  return {
    addresses: [],
    selected: [],
    async loadAddresses() {
      const res = await fetch('/api/v1/admin/addresses/search', {
        headers: { 'X-API-Key': window.apiKey }
      });
      this.addresses = (await res.json()).items;
    },
    selectAll(checked) {
      this.selected = checked ? this.addresses.map(a => a.rc_code) : [];
    },
    openBulkDialog() { /* atidaro modal'ą */ }
  }
}
</script>
```

Visa lentelė su žymėjimu — vienas HTML failas, jokio bundle'inimo.

### 8.2. Plugin'o struktūra

```
/lms-plugin-addresses
  /lib
    /ApiClient.php             # Guzzle klientas Python API'ui
    /Controllers
      /AddressController.php
      /ZoneController.php
      /TechnologyController.php
      /UserController.php
      /BulkOperationController.php
      /AuditController.php
    /Services
      /ApiKeyService.php       # API key generavimas, bcrypt hash, validacija
      /SessionAuthService.php  # LMS sesijos integracija
  /templates                   # Smarty template'ai su Alpine atributais
    /addresses.tpl
    /zones.tpl
    /technologies.tpl
    /users.tpl
    /audit.tpl
    /partials                  # HTMX fragmentų grąžinimui
      /address_row.tpl
      /bulk_preview.tpl
  /assets
    /js
      /alpine.min.js           # Alpine.js (lokali kopija)
      /htmx.min.js             # HTMX (lokali kopija)
      /app.js                  # Custom Alpine komponentų funkcijos
    /css
      /plugin.css              # Plugin'o stiliai
  /db
    /install.sql               # Plugin'o lentelės LMS DB'je (jei reikia)
  /plugin.php                  # LMS hook'ų registracija
  /menu.xml                    # LMS meniu integracija
  /README.md
```

### 8.3. Pagrindiniai ekranai

Visi ekranai naudoja tą patį Alpine + HTMX stack'ą — vienas nuoseklus mokymas, vienas debugging'o stilius.

| Ekranas | Pagrindinis įrankis | Aprašymas |
|---|---|---|
| Adresų valdymas | Alpine (kompleksiška) | Paieška, filtrai, grupinis žymėjimas, preview, undo |
| Zonų valdymas | Alpine + HTMX | Sąrašas, kūrimas, redagavimas (be žemėlapio MVP'e) |
| Technologijų katalogas | HTMX (paprastas CRUD) | Tipų ir variantų valdymas |
| Vartotojai | HTMX (paprastas CRUD) | Vartotojų ir API key'ų valdymas (tik admin rolei) |
| Audit log | HTMX (paprasta peržiūra) | Pakeitimų istorija su filtrais |
| Bulk operacijos | HTMX (peržiūra + rollback) | Grupinių operacijų istorija |

### 8.4. Vartotojai ir rolės

Plugin'as turi savo vartotojų sistemą, nepriklausomą nuo LMS:

- LMS'e darbuotojas turi prieigą prie plugin'o (per LMS leidimus)
- Plugin'o viduje admin'as sukuria mūsų sistemos vartotojus su rolėmis:
  - `admin` — viskas, įskaitant vartotojų valdymą
  - `editor` — kasdienis paslaugų valdymas, grupinės operacijos
  - `viewer` — tik žiūrėjimas

LMS sesija identifikuoja, kuris darbuotojas naudoja plugin'ą. Plugin'as paima jo API key'ą iš `api_keys` lentelės pagal `lms_username` susiejimą:

```php
$lmsUser = $LMS->getUserInfo();  // LMS API
$apiKey = $apiKeyService->getActiveKeyForUser($lmsUser['login']);
$apiClient->setApiKey($apiKey);
```

Iš pradžių (pirmas kartas) admin'as turi sukurti mūsų sistemos vartotoją plugin'e ir nurodyti, su kuriuo LMS vartotoju jis susietas. Tai daro per vartotojų valdymo ekraną.

### 8.5. Adresų valdymo ekranas (pagrindinis)

Smarty template'as `addresses.tpl` su Alpine.js komponentu (žr. 8.1 pavyzdį). Sudedamosios dalys:

**Paieškos filtrai (kairėje pusėje arba viršuje):**
- Rajonas (savivaldybė) — dropdown
- Gyvenvietė — autocomplete iš `localities`
- Gatvė — autocomplete iš `streets`
- Namo numerio diapazonas / patternas
- Technologijos tipas (FIBER, ETHERNET, WIRELESS, LTE)
- Technologijos variantas — filtruojamas pagal tipą (XGPON, GPON ir t.t.)
- Statusas (available / planned / under_construction / unavailable / none)
- Data (planuojama iki)

**Lentelė (centre):**
- Checkbox eilutės žymėjimui
- „Pažymėti visus matomus" (puslapyje, max 100)
- „Pažymėti VISUS rezultatus" (su patvirtinimu, jei >500)
- Skaitiklis viršuje: „Pažymėta: X iš Y"
- Stulpeliai: Adresas, Pašto kodas, Technologija (badge'ai pagal tipą), Statusas, Greitis, Data
- Eilutė plečiama — rodo visą paslaugų sąrašą tam adresui

**Grupinės operacijos toolbar (viršuje, kai pažymėta):**
- Dropdown su operacijomis:
  - Pridėti technologiją
  - Keisti statusą
  - Keisti planuojamą datą
  - Keisti pastabas
  - Pašalinti technologiją
- „Vykdyti" → preview dialogas (modal) → patvirtinimas → execute

### 8.6. Patvirtinimo dialogas

Po preview rodomas modal'as:

```
┌────────────────────────────────────────────┐
│ Patvirtinkit grupinę operaciją             │
│                                            │
│ Bus pakeista:                              │
│   47 adresai · Vilniaus g. 12–24,          │
│   Šalčininkai                              │
│   Technologija: Šviesolaidis GPON          │
│   Statusas: planned → available            │
│                                            │
│ Kada paslauga pradėjo veikti?              │
│   (•) Šiandien (2026-05-15)                │
│   ( ) Kita data: [__________]              │
│                                            │
│ Pastabos (opcionalu):                      │
│   [_____________________________]          │
│                                            │
│         [Atšaukti]  [Vykdyti]              │
└────────────────────────────────────────────┘
```

`status_since` privalomas — istorinis įrašas, kada paslauga pradėjo veikti.

### 8.7. Anuliavimo (undo) juosta

Po sėkmingo vykdymo plugin'o ekrano viršuje:

```
✓ Pakeista 47 adresai · prieš 12 sek · [Anuliuoti operaciją]
```

Galioja 15 min nuo operacijos. Paspaudus — `POST /api/v1/admin/bulk/{id}/rollback`, naudoja `bulk_operations.rollback_data` ir grąžina ankstesnę būseną.

Po 15 min — operacija lieka istorijoje, anuliavimo mygtukas nebematomas. Admin gali atšaukti per „Bulk operacijos" ekraną visada.

### 8.8. Statusų semantika

| Statusas | `status_since` | `planned_until` |
|---|---|---|
| `planned` | Kada įrašytas planas | Kada planuojama prijungti |
| `under_construction` | Kada pradėtas darbas | Numatoma pabaiga |
| `available` | Kada pradėjo veikti | NULL |
| `unavailable` | Kada tapo neprieinama | NULL |

Pereinant tarp statusų — plugin'as klausia vartotojo aktualios datos.

### 8.9. LMS hook'ų integracija

Plugin'as registruojasi į LMS naudodamas standartinę hook'ų sistemą:

```php
// plugin.php
$LMS->executeHook('plugin_register', [
    'name' => 'addresses',
    'menu' => [
        'label' => 'Adresų sistema',
        'icon' => 'map',
        'permissions' => ['addresses_view'],
    ],
]);

$LMS->executeHook('userpanel_lms_initialized', function() use ($LMS) {
    // Plugin'o veiksmai prie LMS inicializacijos
});
```

Vartotojo prieigos kontrolė LMS lygmenyje (per LMS roles), o plugin'o viduje — per mūsų sistemos roles (admin/editor/viewer).

---

## 9. Klientų paieška etanetas.lt

### 9.1. Naudotojo kelias

1. Klientas atvyksta į etanetas.lt
2. Įveda adresą paieškos lauke (autocomplete iš public API)
3. Pasirenka iš pasiūlymo
4. Mato prieinamas paslaugas su greičiais
5. Spaudžia „Susisiekti dėl pasiūlymo" → forma
6. Forma siunčia el. paštą pardavimams (be DB įrašo MVP'e)

### 9.2. UI/UX reikalavimai

- Autocomplete reaguoja po 2+ simbolių, debounce 300ms
- Lietuviškų rašmenų tolerancija (Eišiškės = Eisiskes)
- Rezultatas grupuojamas pagal `public_name`:

```
Vilniaus g. 12, Šalčininkai

  ✓ Šviesolaidis — iki 2 Gbps / 1 Gbps
  ✓ Bevielis — iki 100 Mbps / 30 Mbps

  Planuojama:
  ⏱ Ethernet — bus prieinama 2026-09-01

  [Susisiekti dėl pasiūlymo]
```

### 9.3. Neprieinami adresai

Jei jokia paslauga neprieinama:

```
Vilniaus g. 99, Šalčininkai

  Šiame adrese šiuo metu paslaugų neteikiame.

  [Palikti kontaktą — pranešime kai atsiras galimybė]
```

Forma siunčia el. paštą pardavimams su adresu ir kontaktais. MVP'e jokio DB įrašo.

---

## 10. Duomenų importas iš RC

### 10.1. Šaltinis

**Pirminis:** `get.data.gov.lt` Saugykla (Spinta API)
**Atsarginis:** RC tiesioginiai ZIP failai (registrucentras.lt)

Atvirieji duomenys, CC BY 4.0 licencija. Privaloma nurodyti šaltinį etanetas.lt tinklapyje:

> Adresų duomenys: VĮ Registrų centras (CC BY 4.0)

### 10.2. ETL struktūra

```
/etl
  /downloaders
    spinta_client.py        # Saugyklos API klientas
    rc_zip_fallback.py      # Atsarginis ZIP atsisiuntimas
  /transformers
    address_mapper.py       # data.gov.lt → DB modelio
    geometry_converter.py   # LKS-94 → WGS84 jei reikia
  /loaders
    upsert_load.py          # Bulk upsert į DB
    incremental_load.py     # Changes API processing
  /tasks
    full_import.py          # Pradinis užkrovimas
    nightly_sync.py         # Cron task
    monthly_full_resync.py  # Mėnesinis atsarginis full sync
  config.yaml
  README.md
```

### 10.3. Pradinis užkrovimas

Paleidžiama vieną kartą diegimo metu:

```bash
python -m etl.tasks.full_import
```

Žingsniai:

1. Atsisiunčiamas pilnas adresų rinkinys per Spinta API su puslapiavimu:
   ```
   GET https://get.data.gov.lt/datasets/gov/rc/ar/.../AdresasTaskas?limit(10000)
   ```
2. Iteracija per visus puslapius (~210 puslapių LT mastu)
3. Įrašoma į PostgreSQL atomiškai (transakcija per kiekvieną puslapį)
4. Sukuriami indeksai (po duomenų užkrovimo greičiau)
5. Saugomas paskutinis `_cid` (changes cursor) konfigūracijos lentelėje

Trukmė: ~30-60 min visai LT (~2.1 mln adresų).

### 10.4. Kasnaktinis atnaujinimas

Cron'as `0 2 * * *` (kas naktį 02:00):

```bash
python -m etl.tasks.nightly_sync
```

Žingsniai:

1. Iš DB skaityti paskutinį `_cid`
2. Užklausti changes endpoint:
   ```
   GET https://get.data.gov.lt/datasets/.../AdresasTaskas/:changes/<paskutinis_cid>
   ```
3. Iteracija per pakeitimus, upsert į DB
4. Trūkstami adresai (kurie buvo, bet nebėra) — `deleted_at = NOW()`
5. Saugomas naujas `_cid`

Trukmė: sekundės-minutės (kelių šimtų pakeitimų LT mastu).

### 10.5. Mėnesinis full re-sync

Saugumo tinklas. Cron'as `0 3 1 * *` (kas mėnesio 1 d. 03:00):

```bash
python -m etl.tasks.monthly_full_resync
```

Pakartoja pradinį užkrovimą — apsisaugoja nuo galimų kasnaktinio sync klaidų. Egzistuojantys įrašai atnaujinami per UPSERT, naujų adresų pridedama, trūkstamų pažymimi `deleted_at`.

### 10.6. Klaidų valdymas

- Jei kasnaktinis sync nepavyko → retry po 4h, po 8h
- Jei 3 retry nepavyko → admin pranešimas el. paštu + Slack
- Jei DB neatnaujinta >7 dienas → dashboard'e raudonas indikatorius
- Sync proceso klaida niekada nepaveikia API ar paieškos — DB liks ankstesnėj būsenoj


---

## 11. Saugumas ir audit'as

### 11.1. Audit log mechanizmas

Visi pakeitimai automatiškai įrašomi į `audit_log`. Du implementavimo variantai:

**Variantas A — SQLAlchemy event hook'ai (rekomenduojama):**

```python
@event.listens_for(Session, "before_flush")
def log_changes(session, flush_context, instances):
    for obj in session.dirty:
        # Sukurti audit_log įrašą su diff
```

Privalumai: dirba aplikacijos sluoksnyje, JSONB diff'ai gražūs.

**Variantas B — PostgreSQL trigger'iai:**

Privalumai: dirba net jei kažkas tiesiogiai pasinaudoja DB. Trūkumai: sudėtingiau testuoti.

MVP'ui — variantas A.

### 11.2. Bulk operacijų rollback

Mechanika:

1. Prieš execute — surenkamos esamos reikšmės kiekvienam paveikiamam įrašui → `rollback_data` JSONB
2. Vykdomas execute — pakeitimai įrašomi su `bulk_operation_id` nuoroda
3. Rollback (per 15 min editor, visada admin):
   - Skaitomi visi įrašai su `bulk_operation_id = X`
   - Atstatoma iš `rollback_data`
   - Žymima `rolled_back_at`

### 11.3. Rate limiting

- Public API: 60 req/min per IP
- Internal API: 600 req/min per API key
- Bulk execute: 1 op/min per vartotoją, max 5000 paveiktų įrašų

Implementacija per `slowapi` middleware.

### 11.4. Logging

| Lygmuo | Kas log'uojama | Saugojimas |
|---|---|---|
| INFO | Visi API request'ai (be sensitive data) | stdout → log agregatorius |
| WARNING | 4xx atsakymai | stdout |
| ERROR | 5xx, exception'ai | stdout + Sentry (rekomenduojama) |
| AUDIT | Duomenų pakeitimai | `audit_log` DB |

API key'ai NIEKADA nelog'uojami (nei plain text, nei hash).

### 11.5. Infrastruktūros saugumas

- HTTPS visada (Let's Encrypt arba savo CA)
- Internal API pasiekiama tik iš:
  - Vidinio tinklo
  - LMS serverio IP
  - Admin VPN
- Public API pasiekiama iš interneto, bet tik per CDN/reverse proxy
- DB nepasiekiama iš išorės — tik per backend serverį

---

## 12. Etapai ir terminai

Preliminari etapų lentelė. Tikslūs terminai priklauso nuo komandos pajėgumo.

### Etapas 1: Pamatas (2-3 sav.)

- Repository struktūra, Docker setup
- PostgreSQL + PostGIS instaliacija
- Alembic migracijos (visa schema)
- Pradiniai duomenys (technology_types, technologies)
- CLI super-admin sukūrimas
- Bazinis FastAPI projektas su health endpoint

**Rezultatas:** veikianti tuščia DB, API atsako.

### Etapas 2: RC importas (2-3 sav.)

- Spinta SDK klientas
- Pradinis užkrovimas
- Changes API processing
- Nightly sync cron
- Error handling, retry logika
- Manual paleidimas + testai

**Rezultatas:** DB užkrauta visa LT, kasnaktis sync veikia.

### Etapas 3: Public API (1-2 sav.)

- `/addresses/search` su autocomplete
- `/addresses/{rc_code}/availability`
- Užklausų logika (address_offerings → zone_offerings prioritetas)
- Rate limiting, CORS
- OpenAPI dokumentacija

**Rezultatas:** Public API veikia, testuojama curl/Postman.

### Etapas 4: Internal API ir auth (2-3 sav.)

- API key autentifikacija
- Vartotojų valdymas
- Adresų / zonų / paslaugų CRUD
- Audit log mechanizmas
- Bulk operacijų preview/execute/rollback

**Rezultatas:** Visi admin endpoint'ai veikia.

### Etapas 5: LMS Plus plugin'as (3-4 sav.)

- Plugin'o skeleton'as ir LMS hook'ų registracija
- ApiClient.php — Guzzle klientas Python API'ui
- Sesijos integracija (LMS sesija → mūsų API key)
- Alpine.js + HTMX integracija į LMS Smarty template'us
- Adresų valdymo ekranas: paieška, filtrai, lentelė, žymėjimas (Alpine)
- Grupinių operacijų preview + execute + undo juosta
- Zonų valdymas (HTMX + Alpine)
- Technologijų katalogas (HTMX)
- Vartotojų ir API key'ų valdymas (HTMX, tik admin rolei)
- Audit log peržiūra (HTMX)
- Plugin'o instaliacijos dokumentacija

**Rezultatas:** Darbuotojai naudoja sistemą per LMS Plus, nereikia atskiros aplikacijos.

Trukmė trumpesnė nei Vue/React variantas (3-4 sav. vs 4-5) — be build pipeline'o ir mokymosi.

### Etapas 6: Klientų paieška etanetas.lt (1-2 sav.)

- Integracija į esamą tinklapį
- Autocomplete komponentas
- Prieinamumo atvaizdavimas
- Kontakto forma su email pardavimams
- A/B testavimas (jei reikia)

**Rezultatas:** Klientai gali ieškoti, sistema gyva.

### Etapas 7: Stabilizacija ir paleidimas (1-2 sav.)

- Stress testai
- Saugumo auditas
- Backup strategijos
- Monitoring setup (Sentry, uptime checks)
- Dokumentacija komandai
- Paleidimas į produkciją

**Rezultatas:** Sistema veikia produkcijoje.

**Bendras laikas:** 12-19 savaičių (~3-5 mėn.) priklausomai nuo komandos dydžio.

---

## 13. Atviri klausimai

Klausimai, paliekami vėlesnėms iteracijoms arba paaiškinimui prieš startą.

### 13.1. Vėlesnėms iteracijoms

| Tema | Komentaras |
|---|---|
| **Žemėlapio UI** | MapLibre + OSM tile'ai. Zonų piešimas su poligono įrankiu. Adresų žymėjimas spalvotai. |
| **LMS klientų užsakymai** | Iš tinklapio paieškos → automatinis LMS sutarties juodraštis. |
| **LMS vartotojų sinchronizacija** | Šiandien atskira `users` lentelė. Ateityje — automatinis sinchronizavimas iš LMS. |
| **SSO autentifikacija** | OAuth2 / OIDC integracija. Microsoft Entra ID arba kitas provider'is. Pakeis API key'us. |
| **Buto-lygmens granuliacija** | Šiandien adreso lygmuo. Jei pasimatys, kad reikia, pridėsim `apartment` lentelę. |
| **Talpos tracking'as** | Bazinių stočių apkrovimas, FTTB switch'ų portų užimtumas. |
| **Mobili admin aplikacija** | Techniniam personalui lauke. |
| **Klientų leads DB** | Jei email pardavimams pasirodys neefektyvus. |
| **Statistikos dashboard** | Padengimo procentai pagal regionus, plėtros progresas. |

### 13.2. Reikia paaiškinti prieš startą

| Tema | Klausimas | Kam atsakyti |
|---|---|---|
| Hostingas | Vidinis serveris ar VPS? | IT vadovas |
| Domain'as | API kur priglobs (api.etanetas.lt)? | IT |
| Backup | Strategija (kaip dažnai, kur saugoma)? | IT |
| Monitoring | Sentry, Grafana, kitos priemonės? | DevOps |
| GDPR | Klientų email iš formos — kokia retencija? | Compliance |
| Tinklapio dizainas | Klientų paieškos UI komponento dizainas | Marketingas + UX |

---

## Priedas A: Pavyzdys užklausa nuo galo iki galo

**Scenarijus:** klientas tinklapyje ieško Vilniaus g. 12 Šalčininkuose.

1. **Klientas įveda „Vilniaus 12 Šalč"**
   ```
   GET /api/v1/public/addresses/search?q=Vilniaus%2012%20%C5%A0al%C4%8D
   ```

2. **API atsakymas:**
   ```json
   [
     {
       "rc_code": 12345678,
       "full_address": "Vilniaus g. 12, Šalčininkai",
       "postal_code": "17112"
     },
     ...
   ]
   ```

3. **Klientas spaudžia pirmą rezultatą:**
   ```
   GET /api/v1/public/addresses/12345678/availability
   ```

4. **Backend užklausa DB** (žr. 5.1):
   - Patikrina address_offerings (gauna 1 įrašą: FIBER GPON, available, 2 Gbps)
   - Patikrina service_zones, kurios dengia adreso tašką
   - Iš zone_offerings ima technologijas, kurių NĖRA address_offerings (WIRELESS available, ETHERNET planned)
   - Grupuoja pagal technology_types.public_name

5. **API atsakymas:**
   ```json
   {
     "address": {
       "rc_code": 12345678,
       "full_address": "Vilniaus g. 12, Šalčininkai",
       "postal_code": "17112"
     },
     "available": [
       {"technology": "Šviesolaidis", "max_dl_mbps": 2000, "max_ul_mbps": 1000},
       {"technology": "Bevielis", "max_dl_mbps": 100, "max_ul_mbps": 30}
     ],
     "planned": [
       {"technology": "Ethernet", "planned_until": "2026-09-01"}
     ]
   }
   ```

6. **Tinklapis atvaizduoja:**

   > **Vilniaus g. 12, Šalčininkai**
   >
   > ✓ Šviesolaidis — iki 2 Gbps / 1 Gbps
   > ✓ Bevielis — iki 100 Mbps / 30 Mbps
   >
   > _Planuojama:_
   > ⏱ Ethernet — bus prieinama 2026-09-01
   >
   > [Susisiekti dėl pasiūlymo]

---

## Priedas B: Pavyzdys grupinė operacija

**Scenarijus:** techninė komanda nutiesė šviesolaidį visoje Eišiškių g. (50 namų).

1. **Adminas atidaro adresų valdymo ekraną**
2. **Filtruoja:** gyvenvietė = Eišiškės, gatvė = Eišiškių g.
3. **Pamato 50 rezultatų, pažymi visus**
4. **Pasirenka operaciją:** „Pridėti technologiją"
5. **Užpildo formą:**
   - Technologija: Šviesolaidis GPON
   - Statusas: available
   - Greitis: 1000 / 500 Mbps
6. **Spaudžia „Vykdyti"**
7. **Preview dialogas:**
   ```
   Bus pridėta:
     50 adresai · Eišiškių g. 1-50, Eišiškės
     Technologija: Šviesolaidis GPON
     Statusas: available
     Greitis: 1000 / 500 Mbps

     Kada paslauga pradėjo veikti?
     (•) Šiandien (2026-05-15)
     ( ) Kita data: [____________]

   [Atšaukti]  [Vykdyti]
   ```
8. **Adminas patvirtina**
9. **Backend procesas:**
   - Sukuria bulk_operations įrašą su rollback_data
   - Insert'ina 50 address_offerings įrašus su bulk_operation_id
   - Įrašo 50 audit_log įrašų
10. **Sėkmės pranešimas:**
    ```
    ✓ Pakeista 50 adresų · prieš 2 sek · [Anuliuoti operaciją]
    ```
11. **Jei adminas spaudžia „Anuliuoti" per 15 min — visi 50 įrašų ištrinami, atstatoma ankstesnė būsena**

---

**Dokumentas paruoštas. Sutarus, pradedamas Etapas 1.**

