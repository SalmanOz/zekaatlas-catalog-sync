# ZekâAtlas kaynak kontrolü

Bu klasör bağımsız [`zekaatlas-catalog-sync`](https://github.com/SalmanOz/zekaatlas-catalog-sync) GitHub reposunun köküne taşınmak üzere hazırlanmıştır. Python 3.13 ve standart kütüphane kullanır; ücretli API, scraping servisi veya üçüncü taraf Python paketi gerekmez.

Her gün 06:37 Türkiye saatiyle 30 resmi ürün kaynağı kontrol edilir ve Hugging Face'in herkese açık Spaces listesinden en fazla 10 yeni araç adayı alınır. Başlık, kısa açıklama, HTTP durumu ve kontrol zamanı bir batch oluşturur. Site gönderim ayarları tamamlandıysa batch imzalı olarak ZekâAtlas'a gönderilir; ayarlar eksikse workflow yalnız kontrol yapar. Çalıştırma elle de başlatılabilir. Günlük public metadata raporu `data/latest.json` dosyasına kaydedilir; dosya değiştiyse ayrı GitHub Actions işi bu tek dosyayı commit eder. Fiyatlar ve Türkçe editoryal açıklamalar kendiliğinden yeniden yazılmaz; yeni adaylar editör onayından önce yayımlanmaz.

Resmi sayfanın favicon/apple-touch-icon bağlantısı ve Open Graph/Twitter görsel metadata'sı da izlenir. Yalnız manifest'teki tam `media_hosts` CDN izin listesi ve mevcut resmi kaynak hostları kabul edilir. URL çözümü, public DNS/IP sabitleme, robots ve redirect kontrollerinden sonra image MIME türü ve HTTP 200 erişimi `HEAD` ile doğrulanır; günlük workflow görsel dosyasını indirmez. Geçerli gözlem `source_metadata.media = {"logo_url": "https://...", "preview_image_url": "https://..."}` alanını kullanır; bulunmayan veya erişilemeyen anahtarlar atlanır. Yeni/izinsiz CDN adresi tüm batch'i bozmak yerine medya gözleminden çıkarılır. Site bu değişiklikleri yönetici incelemesine sunar; editörün seçtiği yerel logo ve kullanım görselinin üzerine yazmaz. Hugging Face'in mevcut public liste yanıtı thumbnail sağlamadığından keşif adaylarına uydurma görsel eklenmez.

## Kurulum

1. Bu klasörün içeriğini ayrı bir GitHub reposunun köküne koy. `.github/workflows/catalog.yml` varsayılan dalda olmalı.
2. Repo **Settings → Secrets and variables → Actions** altında `INGEST_SECRET` secret ekle. Laravel `.env` içindeki `INGEST_SECRET` ile aynı, rastgele ve en az 32 karakterli değer kullan.
3. Aynı yerde `INGEST_ENDPOINT` repository variable ekle: `https://site-adresin/api/ingest/tools`.
4. **Actions → Check official AI tool sources → Run workflow** ile ilk kontrolü başlat. Site henüz hazır değilse secret ve variable eklemeden çalıştırabilirsin; bu durumda dry-run ve public rapor commit'leri çalışır. İki ayar da eklendiğinde imzalı gönderim kendiliğinden etkinleşir.
5. Job summary'deki erişim ve engel sayılarını incele. Ürün sayfasının robots veya bot engeli varsa crawler sınırı aşmaya çalışmaz.

GitHub secret'ın içeriğini manifest'e, komut satırına veya repoya yazma. Workflow secret'ı yalnız gönderim adımına aktarır; çıktılar imzayı veya secret'ı loglamaz. Kaynak kontrolü işi yalnız `contents: read` iznine sahiptir. Public raporu commit eden ayrı iş yalnız `contents: write` izni alır; bu işte ingestion secret bulunmaz. Checkout token'ı kalıcı git yapılandırmasına kaydedilmez. Git push token'ı yalnız commit adımında ortamdan askpass ile aktarılır.

## Yerelde doğrulama

```sh
python3 -m unittest discover -s tests -v
python3 crawler.py --limit 3 --no-discovery
```

Gerçek gönderim için `INGEST_ENDPOINT` ve `INGEST_SECRET` ortam değişkenlerini güvenli terminal oturumunda ayarla, ardından `python3 crawler.py --send` çalıştır. Varsayılan CLI çalıştırması siteye yazmaz. `python3 crawler.py` tüm manifest'i ve Spaces keşfini çalıştırır; `--no-discovery` yalnız manifest kontrolünü seçer. Sonuç `out/observations.json` içine kaydedilir ve git tarafından yok sayılır. `python3 public_snapshot.py` komutu raporu izinli alan ve kaynaklarla yeniden doğrular, yalnız public metadata alanlarını `data/latest.json` içine yazar. Aynı rapor dosyayı yeniden yazmaz.

## Kaynak ve yeni araç ekleme

`manifest.json` yalnız editörün onayladığı resmi, herkese açık kaynaklar içerir. Bir kayıt şöyledir:

```json
{
  "slug": "example-tool",
  "url": "https://example.com/",
  "source_url": "https://example.com/product",
  "allowed_hosts": ["example.com"],
  "media_hosts": ["official-product-cdn.example"]
}
```

`url` katalogdaki resmi araç adresidir; `source_url` kontrol edilecek resmi bilgi sayfasıdır. Redirect'in geçeceği alan adları da açıkça `allowed_hosts` listesine eklenir. Wildcard ve alt alan adı eşleştirmesi yoktur. Liste run başına en fazla 40 kaynak içerir. Editör onayladığı yeni resmi ürün kaynağını buraya ekleyebilir; bilinmeyen slug siteye gönderildiğinde moderasyon kuyruğuna girer.

Her araç için en fazla 10 `media_hosts` kaydı olabilir. Yeni medya hostu hem bu listede hem Laravel `media.allowed_hosts` listesinde doğrulanıp eklenmelidir. Sayfa HTML'sindeki keyfi dış bağlantılar kendiliğinden izin listesine alınmaz. İlk katalog görselleri `public/media/{slug}` altında PNG/WebP olarak sunulur; resmi SVG marka kaynakları aktif içerik/dış referans kontrolünden sonra rasterlaştırılmıştır. Bu yerel dosyalar scraper reposunda bulunmaz; scraper yalnız kaynak metadata'sı gözlemler.

Varsayılan keşif bağlantısı yalnız [`GET https://huggingface.co/api/spaces?sort=trendingScore&direction=-1&limit=10`](https://huggingface.co/api/spaces?sort=trendingScore&direction=-1&limit=10) adresini okur. Güncel [Hub API belgeleri](https://huggingface.co/docs/hub/api) ve [Spaces listeleme referansı](https://huggingface.co/docs/huggingface_hub/en/package_reference/hf_api#huggingface_hub.HfApi.list_spaces) bu resmi public listeleme imkanını açıklar. Token, ücretli inference veya Space uygulaması çalıştırma kullanılmaz. Yanıtın en fazla 10 öğesi kabul edilir; `private`, `disabled` veya `gated` işaretli kayıtlar ve hata/durdurma runtime durumları atlanır. URL'ler API'nin keyfi bağlantılarından alınmaz, doğrulanmış `owner/space` kimliğinden yalnız `https://huggingface.co/spaces/owner/space` biçiminde üretilir. Slug `hf-` ile başlar ve en fazla 80 karakterdir. Yalnız varsa kısa card metadata açıklaması alınır; README ve diğer içeriklerin tamamı kopyalanmaz.

Keşif robots engeli, erişim hatası veya geçersiz yanıt nedeniyle yapılamazsa manifest kontrolü ve raporu devam eder. API listelemesinden gelen `reachable=true`, adayın public listede görüldüğünü belirtir; Space uygulamasının çalıştığına dair bir test değildir. `discovered_from_huggingface_api` kaynağı bunu ayırt eder. Public rapor doğrulayıcısı keşif kayıtları için yalnız aynı Hugging Face `/spaces/owner/space` adresi ve bu kimliğe ait slug eşleşmesine izin verir; tüm Hugging Face URL'lerini kabul eden wildcard yoktur.

Site mevcut bir slug için yalnız kontrol metadata'sını günceller. Başlık veya meta açıklama değişiklikleri yönetim panelinde inceleme uyarısı oluşturur. Yeni slug backend'in izin verdiği resmi alan adı listesindeyse araç gönderimi moderasyonuna düşer; tekrar gelen aynı adres yeni bir gönderim oluşturmaz. Editör kategori, Türkçe açıklama, kullanım örnekleri ve fiyat bilgisini inceleyip yayımlama kararı verir. Kullanıcı araç gönderimleri de aynı ayrı moderasyon akışına girer. `huggingface.co` backend izin listesinde bulunur; başka bir alan adı eklenirse Laravel `ingest.allowed_hosts` listesine de eklenmelidir.

## Tarama sınırları

- Yalnız HTTPS ve tam alan adı izin listesi; kullanıcı bilgili URL ve 443 dışı portlar reddedilir.
- Her DNS cevabı public IP olmalı. Bağlantı doğrulanan IP'ye sabitlenir ve TLS sertifikası resmi host adına göre doğrulanır. Private IP veya karışık public/private DNS cevabı reddedilir.
- Redirect hedefi için de URL, host, DNS ve robots kontrolü yapılır. En fazla 3 redirect izlenir.
- `robots.txt` izinleri, crawl-delay ve request-rate dikkate alınır. Robots 404 ise kamuya açık sayfa kontrolüne izin verilir; diğer robots erişim hatalarında kaynak kontrolü yapılmaz.
- Yalnız editörün açıkça doğruladığı statik medya CDN'lerinde robots 400/403/410 yanıtı eksik dosya olarak değerlendirilir; [RFC9309 §2.3.1.3](https://www.rfc-editor.org/rfc/rfc9309.html#section-2.3.1.3) bu durumda public kaynağa erişime izin verir. Gerçek `Disallow` kuralları uygulanır; 401, 429, 5xx, ağ hatası veya robots yerine HTML challenge gelirse görsel kontrolü atlanır. Görselin kendisinin 403 yanıtı hiçbir şekilde aşılmaz. Kaynak sayfası taramasında bu CDN istisnası uygulanmaz.
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
        "final_url": "https://example.com/product",
        "media": {
          "logo_url": "https://official-product-cdn.example/logo.png",
          "preview_image_url": "https://official-product-cdn.example/preview.webp"
        }
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
