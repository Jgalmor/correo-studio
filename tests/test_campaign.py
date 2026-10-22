import unittest
import json
import threading
from http.client import HTTPConnection
from unittest.mock import patch

from campaign import analyze_page, readable_color, render_email, validate_url
from server import create_server


PAGE = '''<!doctype html><html lang="es"><head>
<title>Atelier Norte | Diseño que acompaña</title>
<meta name="description" content="Muebles hechos a mano para espacios que se viven.">
<meta property="og:image" content="/assets/coleccion.jpg">
<meta name="theme-color" content="#173E38">
<link rel="icon" href="/assets/favicon.png">
<style>:root { --brand-primary: #173E38; }</style>
</head><body><header><img alt="Atelier Norte logo" src="/assets/logo.png"></header>
<main><h1>Muebles hechos a mano para espacios que se viven</h1>
<h2>Diseñados para durar</h2><p>Piezas creadas con madera recuperada y acabados naturales.</p>
<a href="/coleccion">Descubrir la colección</a></main></body></html>'''


class CampaignTests(unittest.TestCase):
    def test_page_becomes_branded_email_with_actual_claims(self):
        data = analyze_page("https://atelier.example/", PAGE)
        html = render_email(data)
        self.assertIn("https://atelier.example/assets/logo.png", html)
        self.assertIn("https://atelier.example/assets/coleccion.jpg", html)
        self.assertIn("Muebles hechos a mano para espacios que se viven", html)
        self.assertIn("Diseñados para durar", html)
        self.assertIn("#173E38", html)
        self.assertIn("https://atelier.example/coleccion", html)
        self.assertIn("{{unsubscribe_url}}", html)
        self.assertIn("{{sender_address}}", html)
        self.assertIn('role="presentation"', html)

    def test_unsafe_urls_are_rejected(self):
        for url in ("file:///etc/passwd", "http://127.0.0.1/", "http://localhost/", "https://user:pass@example.com/"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_url(url)

    def test_untrusted_copy_is_escaped_and_tracking_links_rejected(self):
        page = '<html><head><title>&lt;script&gt;alert(1)&lt;/script&gt;</title></head><body><h1>Oferta &lt;b&gt;real&lt;/b&gt;</h1><a href="javascript:alert(1)">Compra</a></body></html>'
        html = render_email(analyze_page("https://example.com/", page))
        self.assertNotIn("<script>", html)
        self.assertNotIn("javascript:", html)
        self.assertIn("Oferta &lt;b&gt;real&lt;/b&gt;", html)

    def test_cookie_consent_copy_is_not_used_as_a_claim(self):
        page = '''<html><body><div class="cookie-consent"><h1>We use cookies to improve your experience</h1><p>Accept cookies for analytics and marketing purposes.</p></div><main><h1>Furniture crafted for everyday life</h1><h2>Made from reclaimed wood</h2></main></body></html>'''
        data = analyze_page("https://example.com/", page)
        self.assertEqual(data["headline"], "Furniture crafted for everyday life")
        self.assertEqual(data["claims"], ["Made from reclaimed wood"])

    def test_icon_file_is_not_treated_as_an_email_logo(self):
        page = '<html><head><link rel="icon" href="/favicon.ico"></head><body><h1>Made with care</h1></body></html>'
        data = analyze_page("https://example.com/", page)
        self.assertEqual(data["logo"], "")

    def test_maintenance_page_is_not_presented_as_marketing_copy(self):
        page = '<html><head><title>Hang Tight! Routing to checkout...</title></head><body><h1>We are temporarily unavailable</h1><p>This page will automatically refresh shortly.</p></body></html>'
        with self.assertRaisesRegex(ValueError, "mantenimiento"):
            analyze_page("https://example.com/", page)

    def test_locale_selector_is_not_a_promotional_claim(self):
        page = '<html><head><meta name="description" content="Independent products crafted for everyday living."></head><body><h1>Choose your language or locale to browse</h1><p>It is available in the following languages:</p></body></html>'
        data = analyze_page("https://example.com/", page)
        self.assertEqual(data["headline"], "Independent products crafted for everyday living.")
        self.assertEqual(data["claims"], [])

    def test_brand_name_containing_shop_is_not_mistaken_for_cta(self):
        page = '<html><body><h1>Crafted essentials for every day</h1><a href="/partners">shopyowie.com</a><a href="/products">Discover the collection</a></body></html>'
        data = analyze_page("https://example.com/", page)
        self.assertEqual(data["cta"], "Discover the collection")
        self.assertEqual(data["destination"], "https://example.com/products")

    def test_nested_heading_text_has_readable_word_boundaries(self):
        page = '<html><body><h1>Be the next<span>AI</span> all-star</h1></body></html>'
        data = analyze_page("https://example.com/", page)
        self.assertEqual(data["headline"], "Be the next AI all-star")

    def test_cta_does_not_follow_unrelated_external_product(self):
        page = '<html><body><h1>Everything for your new store</h1><a href="https://payments.example.net/">Shop Pay</a><a href="/start">Discover the platform</a></body></html>'
        data = analyze_page("https://example.com/", page)
        self.assertEqual(data["cta"], "Discover the platform")

    def test_no_fabricated_claims_when_page_is_sparse(self):
        data = analyze_page("https://example.com/", "<html><body><p>Hola</p></body></html>")
        html = render_email(data)
        self.assertNotIn("envío gratis", html.lower())
        self.assertEqual(data["claims"], [])
        self.assertFalse(data["color_detected"])
        self.assertNotIn("te suscribiste", html)

    def test_theme_color_reports_its_origin(self):
        data = analyze_page("https://example.com/", PAGE)
        self.assertTrue(data["color_detected"])

    def test_light_brand_color_is_darkened_for_readable_button_text(self):
        self.assertLessEqual(int(readable_color("#FFFFFF")[1:3], 16), 118)

    def test_generate_endpoint_returns_preview_and_analysis(self):
        server = create_server("127.0.0.1", 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch("server.fetch_page", return_value=("https://atelier.example/", PAGE)):
                client = HTTPConnection("127.0.0.1", server.server_port)
                client.request("POST", "/api/generate", json.dumps({"url": "https://atelier.example/"}), {"Content-Type": "application/json"})
                response = client.getresponse()
                payload = json.loads(response.read())
                self.assertEqual(response.status, 200)
                self.assertIn("<!doctype html>", payload["html"])
                self.assertEqual(payload["analysis"]["color"], "#173E38")
                client.close()
        finally:
            server.shutdown()
            server.server_close()

    def test_homepage_contains_url_form_preview_and_download(self):
        server = create_server("127.0.0.1", 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            client = HTTPConnection("127.0.0.1", server.server_port)
            client.request("GET", "/")
            response = client.getresponse()
            page = response.read().decode("utf-8")
            self.assertEqual(response.status, 200)
            self.assertIn('type="url"', page)
            self.assertIn('id="generate"', page)
            self.assertIn('id="preview"', page)
            self.assertIn('id="download"', page)
            client.close()
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
