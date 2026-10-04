# ZekâAtlas kaynak kontrolü

Bu klasör bağımsız `zekaatlas-catalog` GitHub reposunun köküne taşınmak üzere hazırlanmıştır. Python 3.13 ve standart kütüphane kullanır; ücretli API, scraping servisi veya üçüncü taraf Python paketi gerekmez.

Her gün 06:37 Türkiye saatiyle 30 resmi ürün kaynağı kontrol edilir. Başlık, meta açıklama, HTTP durumu ve kontrol zamanı imzalı bir batch olarak ZekâAtlas'a gönderilir. Çalıştırma elle de başlatılabilir. Günlük public metadata raporu `data/latest.json` dosyasına kaydedilir; dosya değiştiyse ayrı GitHub Actions işi bu tek dosyayı commit eder. Bu, kaynak metadata kontrolüdür: fiyatları veya Türkçe editoryal açıklamaları kendiliğinden yeniden yazmaz.

## Kurulum

1. Bu klasörün içeriğini ayrı bir GitHub reposunun köküne koy. `.github/workflows/catalog.yml` varsayılan dalda olmalı.
2. Repo **Settings → Secrets and variables → Actions** altında `INGEST_SECRET` secret ekle. Laravel `.env` içindeki `INGEST_SECRET` ile aynı, rastgele ve en az 32 karakterli değer kullan.
3. Aynı yerde `INGEST_ENDPOINT` repository variable ekle: `https://site-adresin/api/ingest/tools`.
4. Site HTTPS üzerinde çalıştıktan sonra **Actions → Check official AI tool sources → Run workflow** ile ilk kontrolü başlat.
5. Job summary'deki erişim ve engel sayılarını incele. Ürün sayfasının robots veya bot engeli varsa crawler sınırı aşmaya çalışmaz.

GitHub secret'ın içeriğini manifest'e, komut satırına veya repoya yazma. Workflow secret'ı yalnız gönderim adımına aktarır; çıktılar imzayı veya secret'ı loglamaz. Kaynak kontrolü işi yalnız `contents: read` iznine sahiptir. Public raporu commit eden ayrı iş yalnız `contents: write` izni alır; bu işte ingestion secret bulunmaz. Checkout token'ı kalıcı git yapılandırmasına kaydedilmez. Git push token'ı yalnız commit adımında ortamdan askpass ile aktarılır.

## Yerelde doğrulama

```sh
python3 -m unittest discover -s tests -v
python3 crawler.py --limit 3
```

Gerçek gönderim için `INGEST_ENDPOINT` ve `INGEST_SECRET` ortam değişkenlerini güvenli terminal oturumunda ayarla, ardından `python3 crawler.py --send` çalıştır. Varsayılan çalıştırma siteye yazmaz. Sonuç `out/observations.json` içine kaydedilir ve git tarafından yok sayılır. `python3 public_snapshot.py` komutu raporu izinli alan ve kaynaklarla yeniden doğrular, yalnız public metadata alanlarını `data/latest.json` içine yazar. Aynı rapor dosyayı yeniden yazmaz.

## Kaynak ve yeni araç ekleme

`manifest.json` yalnız editörün onayladığı resmi, herkese açık kaynaklar içerir. Bir kayıt şöyledir:

```json
{
  "slug": "example-tool",
  "url": "https://example.com/",
  "source_url": "https://example.com/product",
  "allowed_hosts": ["example.com"]
}
```

`url` katalogdaki resmi araç adresidir; `source_url` kontrol edilecek resmi bilgi sayfasıdır. Redirect'in geçeceği alan adları da açıkça `allowed_hosts` listesine eklenir. Wildcard ve alt alan adı eşleştirmesi yoktur. Liste run başına en fazla 40 kaynak içerir. Yeni araçları bu listeye eklemek kaynak seçimi için editör işlemidir; bu ilk sürüm otomatik yeni araç keşfi yapmaz. Sürekli kontrol edilen izinli resmi kaynakların metadata'sını izler. Yeni ürün keşfi için bir editör resmi ürün adresini manifest'e eklemelidir; kullanıcı araç gönderimleri de ayrı moderasyon akışına girer. Böylece otomatik bir bağlantı yanlışlıkla yayımlanmaz.

Site mevcut bir slug için yalnız kontrol metadata'sını günceller. Yeni slug backend'in izin verdiği resmi alan adı listesindeyse araç gönderimi moderasyonuna düşer. Editör onayı olmadan yeni araç yayımlanmaz. Yeni bir alan adı eklenirse Laravel `ingest.allowed_hosts` listesine de eklenmelidir.

## Tarama sınırları

- Yalnız HTTPS ve tam alan adı izin listesi; kullanıcı bilgili URL ve 443 dışı portlar reddedilir.
- Her DNS cevabı public IP olmalı. Bağlantı doğrulanan IP'ye sabitlenir ve TLS sertifikası resmi host adına göre doğrulanır. Private IP veya karışık public/private DNS cevabı reddedilir.
- Redirect hedefi için de URL, host, DNS ve robots kontrolü yapılır. En fazla 3 redirect izlenir.
- `robots.txt` izinleri, crawl-delay ve request-rate dikkate alınır. Robots 404 ise kamuya açık sayfa kontrolüne izin verilir; diğer robots erişim hatalarında kaynak kontrolü yapılmaz.
- Aynı host istekleri arasında en az 2 saniye, robots daha uzun süre isterse o süre beklenir. 120 saniyeden uzun delay bu sınırlı run'da atlanır.
- İstek başına 15 saniye timeout ve 1 MiB yanıt limiti vardır. Sıkıştırılmış yanıtlar işlenmez.
- Login, captcha, anti-bot ekranı ve JavaScript çalıştırma kullanılmaz. Görünen metnin tamamı kopyalanmaz; HTML title/meta description alınır.

`reachable=false`, **crawler'ın kaynağa erişemediği** anlamındadır. `robots_denied`, `robots_unavailable` veya bot engeli bir aracın kapandığını kanıtlamaz. Sitede araç “çevrimdışı” olarak otomatik etiketlenmemelidir. `source_metadata.reason` inceleme için saklanır.

## İmzalı veri sözleşmesi

`POST /api/ingest/tools` gövdesi:

```json
{
  "batch_id": "sha256-of-canonical-deduplicated-observations",
  "checked_at": "2026-10-04T03:37:00+00:00",
  "observations": [
    {
      "slug": "example-tool",
      "url": "https://example.com/",
      "source_url": "https://example.com/product",
      "reachable": true,
      "checked_at": "2026-10-04T03:37:00+00:00",
      "source_metadata": {
        "title": "Official product title",
        "meta_description": "Official short description",
        "status": 200,
        "final_url": "https://example.com/product"
      }
    }
  ]
}
```

`X-Ingest-Timestamp` Unix saniye timestamp'idir. `X-Ingest-Signature`, `INGEST_SECRET` ile `timestamp + "." + exact UTF-8 raw JSON body` üzerinden hesaplanan HMAC-SHA256 hex değeridir. Sunucu en fazla 5 dakika sapmayı kabul eder. Payload canonical JSON olarak seri hale getirilir; batch id slug/source bazında sıralanmış ve tekilleştirilmiş observation listesinin SHA256 hash'idir. Observation kontrol zamanları hash'e dahildir, dolayısıyla yeni günün kontrolü farklı batch üretir.

429 ve geçici 5xx gönderim yanıtları en fazla 3 kez aynı gövde ve batch id ile denenir. Timestamp/imza her denemede yenilenir. İmzalı POST redirect'i takip edilmez. Aynı batch'in yeniden gönderimi sunucuda idempotent olmalıdır.

## Ücretsiz GitHub Actions koşulları

4 Ekim 2026'da resmi GitHub belgelerine göre public repolarda standart GitHub-hosted runner kullanımı ücretsizdir. Private GitHub Free hesapları aylık 2.000 dakika ve 500 MB paylaşılan artifact alanı içerir; aşım faturalandırılabilir. Bu workflow standart `ubuntu-latest` kullanır, artifact veya cache yüklemez; kaynak işini 15, snapshot işini 3 dakika ile sınırlar. İki iş arasındaki rapor aktarımı yalnız sınırlı public metadata içeren job output ile yapılır. Public repo bu iş için ücretsiz kullanımın en anlaşılır seçeneğidir. [GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions)

GitHub schedule çalıştırmaları yoğunlukta gecikebilir veya düşebilir. Public repoda 60 gün repo etkinliği olmazsa zamanlanmış workflow devre dışı bırakılır; yeniden etkinleştirmek gerekir. 06:37 saati garanti edilmiş bir SLA değildir. Workflow varsayılan dalda olmalıdır. [Schedule koşulları](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)

Repo faturasında ek ücret oluşmaması gerekiyorsa private repo kullanımında hesap Actions bütçesini de sıfır harcama için kontrol et. Büyük runner seçilmemeli. Günlük public kaynak raporu kontrol zamanını da içerdiğinden normal günlük kontroller repo etkinliği oluşturan veri commit'leri üretir. Aynı rapor tekrarlanırsa commit oluşmaz. Commit yalnız `data/latest.json` dosyasını içerir; kaynak kodunu veya secrets'ı değiştirmez. 60 gün kuralı, workflow çalışmayı bırakırsa veya branch koruması push'u engellerse hâlâ geçerlidir. Push başarısızlığı workflow'da açık hata verir; daha önce başarıyla gönderilmiş ingestion geri alınmaz. Branch korumasının bu rapor commit'ine izin verdiğini kontrol et; workflow force push yapmaz.
