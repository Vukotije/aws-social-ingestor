# Predmetni projekat: Racunarstvo u oblaku

Kroz predmetni projekat neophodno je implementirati platformu za prikupljanje, procesiranje, cuvanje i analizu podataka sa razlicitih drustvenih mreza i blog portala.

Resenje mora da bude implementirano koristeci AWS platformu. Dizajn procesiranja podataka mora da prati Medallion arhitekturu.

## Funkcionalni zahtevi

### 1. Prikupljanje podataka (bronze layer)

Neophodno je prikupiti podatke sa 2 izvora podataka (datasource):

- Hacker News
- X (Twitter)

#### 1.1. Hacker News izvor podataka

Hacker News predstavlja portal za objavljivanje blogova, vesti i komentara na razlicite teme. Neophodno je na dnevnom nivou prikupiti sve objave (`story`), pitanja (`ask`), komentare (`comment`), ponude za poslove (`job`) i ankete (`poll`) koji su kreirani prethodnog dana.

API je besplatan, a dokumentacija je dostupna ovde. Od koristi moze biti i HN Search API koji pretrazuje portal na osnovu zadatih kljucnih reci.

Prikupljanje podataka treba da se implementira pomocu Lambda funkcije. Funkcija treba da upise prikupljene podatke u S3 bucket u njihovom izvornom obliku. Nikakvo procesiranje ili transformacija podataka nije dozvoljena, jer S3 bucket predstavlja bronze layer Data Lake-a koji je namenjen da cuva podatke u njihovom izvornom obliku.

#### 1.2. X (Twitter) izvor podataka

X (Twitter) je drustvena mreza za objavljivanje mini postova. S obzirom na to da je besplatna verzija X API-ja jako limitirana, mogu se iskoristiti vec postojeci dataset-ovi na Internetu, rucno formirati ili generisati dataset-ovi.

Dataset-ove je neophodno ubaciti u Data Lake bucket. Ovo su neki primeri dataset-ova koji se mogu koristiti, ali nisu obavezni:

- Bitcoin Tweets
- Covid Tweets

### 2. Normalizacija podataka (silver layer)

S obzirom na to da bronze layer Data Lake-a moze da sadrzi podatke u razlicitim formatima i da same strukture podataka mogu biti razlicite, neophodno je te podatke svesti na jedan format i formirati odgovarajucu strukturu podataka, odnosno semu podataka.

Bez formirane seme podataka ne mogu se pisati upiti (`query`) u kasnijim fazama obrade podataka. Ovaj proces se naziva normalizacija podataka.

Implementirati Lambda funkciju ili funkcije koje ce raditi normalizaciju podataka.

Normalizacija obuhvata:

- Poravnjanje ugnjezdenih struktura, na primer `kids` polja u Hacker News objavama.
- Poravnjanje vremena. Hacker News koristi Unix Epoch format (`1736978058`), dok X koristi ISO-8601 (`2026-01-15T21:54:18Z`). Vreme treba da se poravna u jedan UTC format.
- Ciscenje vrednosti podataka. Na primer, u nekim Hacker News objavama postoje HTML tagovi (`<p>`, `<i>`). Te tagove treba pocistiti.
- Uklanjanje duplikata.
- Dodatna procesiranja podataka koja smatrate da su neophodna, a nisu prethodno navedena.
- Uspostavljanje seme, odnosno strukture podataka. Definisati tabele (`dataframe`-ove) sa njihovim kolonama i relacijama izmedju tabela. Po pravilu, sema treba da ima sto manje redundantnosti i da zadovoljava 3NF. Tabele treba sacuvati u Parquet format i particionisati podatke.

Sto se tice uspostavljanja strukture podataka, ona nije jedinstvena i moze se razlikovati u zavisnosti od toga koji podaci su interesantni i imaju benefita. Ova struktura podataka direktno utice na kasnije faze obrade podataka. Bitno je naglasiti da se moze menjati tokom vremena, narocito ako su uoceni nedostaci u semi podataka.

Jedan konkretan primer uspostavljanja strukture podataka bio bi da se sema podataka sastoji od 2 tabele.

#### Primer tabele `users`

| Kolona | Tip | Opis |
| --- | --- | --- |
| `user_id` | UUID | Generisani ID |
| `username` | String | Preuzet sa Hacker News i X platforme |
| `platform` | String | `Hacker News` ili `X` |
| `karma_score` | Integer | Korisnikova reputacija na Hacker News; `null` za X korisnike |
| `is_verified` | Boolean | Da li je korisnik verifikovan na X platformi; `null` za Hacker News korisnike |
| `created_at` | Timestamp | Normalizovan u UTC ISO-8601 formatu |

#### Primer tabele `posts`

| Kolona | Tip | Opis |
| --- | --- | --- |
| `post_id` | String | Originalni ID iz Hacker News ili X platforme |
| `author_username` | String | Strani kljuc ka `users` tabeli |
| `content_text` | String | Sadrzaj objave, sa pociscenim HTML tagovima |
| `created_at` | Timestamp | Normalizovan u UTC ISO-8601 formatu |
| `post_type` | String | `story`, `comment`, `tweet`, `retweet` |

Tabela `users` bi se particionisala po `platform` koloni, dok bi se tabela `posts` particionisala na osnovu timestamp kolone.

Data Lake bucket bi u tom slucaju izgledao ovako:

```text
s3://social-medias/silver/
├── posts/
│   └── year=2026/month=01/day=15/
│       └── data_001.parquet
└── users/
    ├── platform=HackerNews/
    └── platform=X/
```

Za pisanje i citanje u Parquet format moze se koristiti `awswrangler` biblioteka, kao i njen Lambda layer. Konkretan primer particionisanja podataka je dostupan ovde.

### 3. Transformacija podataka (gold layer)

Implementirati Lambda funkciju ili funkcije koje transformisu podatke i kreiraju odredjene metrike i KPI (Key Performance Indicators).

#### Metrike

Izracunati sledece metrike:

- Koliko se dnevno kreira objava (`story`), pitanja (`ask`), komentara (`comment`), ponuda za posao (`job`) i anketa (`poll`) na Hacker News portalu.
- Broj korisnika sa Hacker News portala na dnevnom nivou.
- Broj korisnika sa X platforme na dnevnom nivou.
- Prvih 10 korisnika X platforme sa najvecim brojem pratilaca.
- Prvih 10 korisnika Hacker News portala sa najvecim karma score-om na dnevnom nivou.
- Prvih 10 korisnika Hacker News portala sa najmanjim karma score-om na dnevnom nivou.
- Prvih 10 ponuda za posao na Hacker News portalu sa najvecim score-om na dnevnom nivou.
- Prvih 10 objava na Hacker News portalu sa najvecim score-om na dnevnom nivou.

#### KPI

Izracunati sledeci KPI:

- **Data Quality Score**: pokazuje procentualno koliko redova tabela (`dataframe`-ova) nisu `null`. Ovaj indikator pokazuje koliko je normalizacija podataka dobro uradjena.

Za dizajniranje seme podataka moze se koristiti Star Schema.

Na primer, za pracenje broja korisnika na platformama formirala bi se sledeca tabela.

#### Primer tabele `daily_users_metric`

| Kolona | Tip | Opis |
| --- | --- | --- |
| `date` | date | Datum |
| `platform` | String | `Hacker News` ili `X` |
| `total_users` | Integer | Ukupan broj korisnika na odredjenoj platformi |
| `new_users` | Integer | Broj novih korisnika registrovanih za odredjen dan i platformu |

Primer podataka:

| date | platform | total_users | new_users |
| --- | --- | ---: | ---: |
| 2025-01-15 | Hacker News | 11500 | 100 |
| 2025-01-15 | X | 456 | 74 |
| 2025-01-16 | Hacker News | 12030 | 530 |
| 2025-01-16 | X | 523 | 87 |

Particionisanje bi se radilo po `platform` i `date` koloni:

```text
s3://social-medias/gold/
└── daily_users_metric/
    ├── platform=HackerNews/
    │   ├── date=2026-01-15/
    │   │   └── data_001.parquet
    │   └── date=2026-01-16/
    │       └── data_001.parquet
    └── platform=X/
        ├── date=2026-01-15/
        │   └── data_001.parquet
        └── date=2026-01-16/
            └── data_001.parquet
```

### 4. Vizualizacija podataka

Metrike i KPI koji su nastali transformacijom podataka treba vizualizovati koristeci Apache Superset alat.

S obzirom na to da Apache Superset ne podrzava direktno vizualizaciju podataka sa S3 bucket-a u Parquet formatu, neophodno je metrike i KPI sacuvati u PostgreSQL bazu. Zatim je neophodno konfigurisati Apache Superset da cita podatke iz PostgreSQL baze.

Apache Superset i PostgreSQL treba hostovati na EC2 instanci. Takodje, neophodno je implementirati Lambda funkciju koja ce metrike i KPI iz S3 bucket-a premestati u PostgreSQL bazu na EC2 instanci.

### 5. Notifikacije

Neophodno je namestiti notifikacije ka Discord serveru za sve job-ove koji su pali ili su se neuspesno izvrsili.

Moze se koristiti neka druga platforma za notifikacije; nije obavezno koristiti Discord.

### Napomena o orkestraciji

Moze se koristiti Step Functions servis kako bi se normalizacija i transformacija podataka razdvojile u vise zasebnih koraka, odnosno Lambda funkcija, i time pojednostavila implementacija samih funkcija.

## Nefunkcionalni zahtevi

### 6. Infrastructure as Code (IaC)

Sva infrastruktura mora da bude napisana koristeci neki od IaC alata:

- CDK
- CloudFormation
- Terraform
- Terragrunt

### 7. Kontrola mrezne komunikacije

Celokupna infrastruktura treba da bude implementirana unutar VPC mreze, uz primenu principa najmanjih privilegija (least privilege).

Dozvoljena je iskljucivo minimalno potrebna mrezna komunikacija izmedju servisa koriscenjem sigurnosnih grupa i mreznih pravila.

## Bodovanje

| Stavka | Poeni |
| --- | ---: |
| Prikupljanje podataka (bronze layer) | 10 |
| Normalizacija podataka (silver layer) | 14 |
| Transformacija podataka (gold layer) | 10 |
| Vizualizacija podataka | 8 |
| Notifikacije | 5 |
| Kontrola mrezne komunikacije | 3 |
| **Ukupno** | **50** |

> **Napomena:** Infrastructure as Code (IaC) je eliminacioni zahtev i projekat koji ne ispunjava ovaj zahtev se nece pregledati.

## Pravila polaganja

- Projekat se radi u timovima do 3 clana.
- Projekat mozete implementirati u bilo kom programskom jeziku i radnom okviru. Ako se odlucite za tehnologiju koja nije pokrivena na vezbama, pomoc u tom slucaju je ogranicena.
- Za sve slucajeve koji nisu pokriveni u specifikaciji, studentima se daje mogucnost da ih rese na nacin koji je njima najprikladniji.
- Projekat se polaze kroz kontrolnu tacku koja ce se odrzati u toku semestra i odbranu koja ce se odrzati u ispitnim rokovima: jednom u junsko-julskom ispitnom roku i jednom u avgustovsko-septembarskom ispitnom roku.
