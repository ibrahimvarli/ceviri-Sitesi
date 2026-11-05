# PDF Translate Studio

Modern tasarimli, Python tabanli ve tamamen acik kaynak bilesenlerle gelistirilmis bir PDF ceviri sitesi. Kullanicilar PDF yukler, belge yapisi analiz edilir, yerel ceviri motoru ile hedef dile cevrilir ve sonuc cift sutunlu profesyonel bir PDF dosyasi olarak sunulur.

## Ozellikler

- Flask tabanli moduler web uygulamasi
- Belge analizi icin `PyMuPDF`
- Acik kaynak ceviri motoru olarak `Argos Translate`
- Coklu dil secimi ve otomatik kaynak dil algilama (`langdetect`)
- Taranmis PDF'ler icin `pytesseract` ile OCR uyumu
- Akademik ve teknik terimler icin JSON tabanli terim sozlugu
- Baslik, dipnot, madde isareti ve tablo bloklarini ayristirma
- Solda orijinal, sagda ceviri olacak sekilde cift sutunlu PDF cikti
- Sayfa bazli kaynak ve ceviri onizlemesi
- Modern, responsif arayuz
- Sonucu `.pdf` dosyasi olarak indirme

## Kurulum

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

Ardindan tarayicida `http://127.0.0.1:5000` adresini acin.

## Acik Kaynak Bilesenler

- `Argos Translate`: Ucretsiz ve acik kaynak ceviri motoru
- `LibreTranslate`: Acik kaynak ceviri servis uyumlulugu
- `PyMuPDF`: PDF blok analizi ve duzen okuma
- `ReportLab`: Profesyonel PDF cikti uretimi
- `pytesseract`: OCR baglantisi
- `langdetect`: Otomatik kaynak dil algilama

## OCR Notu

OCR katmani acik kaynak `Tesseract OCR` uzerine kuruludur. Windows'ta ayrica Tesseract kurmaniz gerekir. Kurulumdan sonra isterseniz `.env` icinde `TESSERACT_CMD` yolunu belirtebilirsiniz.

## Ceviri Motoru Notu

Sistem acik kaynak ceviri zinciri kullanir:

- Once yerel `Argos Translate`
- Sonra yerel `Helsinki-NLP Transformers`
- Gerekirse `LibreTranslate` uyumlu servis

Varsayilan olarak resmi `https://libretranslate.com/translate` adresi denenir; gerekirse `.env` icinde ozel bir `LIBRETRANSLATE_URL` tanimlanabilir.

## Terim Sozlugu

Varsayilan terim sozlugu dosyasi `app/data/glossary.json` altindadir. Dil ciftine gore terimler tanimlanabilir:

```json
{
  "en:tr": {
    "machine learning": "makine ogrenmesi"
  }
}
```

## Proje Yapisi

```text
app/
  data/
  routes/
  services/
  static/
  templates/
  utils/
run.py
requirements.txt
```

## Notlar

- Varsayilan ceviri zinciri acik kaynak motorlardan olusur; ilk calismada yerel dil paketleri veya modeller indirilebilir.
- Tesseract kurulu degilse OCR adimi sessizce atlanir; normal metin tabanli PDF'ler yine islenir.
- Belge analizi heuristik tabanlidir; cok karmasik tablolar ve dergi duzeni belgelerde daha ileri ayarlama gerekebilir.
