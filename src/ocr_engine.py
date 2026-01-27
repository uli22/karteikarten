"""OCR Engine für Handschrifterkennung auf Karteikarten."""

import json
import os
from pathlib import Path
from typing import Optional

import easyocr
import numpy as np
import pytesseract
from PIL import Image, ImageEnhance, ImageFilter

from .text_postprocessor import TextPostProcessor

try:
    from google.cloud import vision
    from google.oauth2 import service_account
    CLOUD_VISION_AVAILABLE = True
except ImportError:
    CLOUD_VISION_AVAILABLE = False


class OCREngine:
    """Engine für Optical Character Recognition auf deutschen Handschriften."""
    
    def __init__(self, ocr_method: str = 'easyocr', preprocess: bool = True, 
                 credentials_path: Optional[str] = None, enable_postprocessing: bool = True):
        """
        Initialisiert die OCR Engine.
        
        Args:
            ocr_method: 'easyocr', 'tesseract', oder 'cloud_vision'
            preprocess: Wenn True, wird Bildvorverarbeitung durchgeführt
            credentials_path: Pfad zur Google Cloud Credentials JSON-Datei
            enable_postprocessing: Wenn True, wird Text-Nachbearbeitung angewendet
        """
        self.ocr_method = ocr_method
        self.preprocess = preprocess
        self.reader = None
        self.vision_client = None
        # WICHTIG: Post-Processor wird immer initialisiert
        self.postprocessor = TextPostProcessor()
        
        if ocr_method == 'easyocr':
            # EasyOCR ist besser für Handschrift
            print("Initialisiere EasyOCR für Deutsch...")
            self.reader = easyocr.Reader(['de'], gpu=False)
        
        elif ocr_method == 'cloud_vision':
            if not CLOUD_VISION_AVAILABLE:
                raise ImportError("google-cloud-vision ist nicht installiert. Installieren Sie es mit: uv add google-cloud-vision")
            
            # Prüfe Credential-Typ und initialisiere entsprechend
            if credentials_path and Path(credentials_path).exists():
                cred_type = self._check_credential_type(credentials_path)
                
                if cred_type == 'service_account':
                    # Service Account - direkt nutzen
                    credentials = service_account.Credentials.from_service_account_file(credentials_path)
                    print("Initialisiere Google Cloud Vision API mit Service Account...")
                    self.vision_client = vision.ImageAnnotatorClient(credentials=credentials)
                
                elif cred_type == 'oauth2_client':
                    # OAuth2 Client Secret - Fehler mit Anleitung
                    raise ValueError(
                        "Sie haben eine OAuth2-Client-Secret-Datei ausgewählt.\n\n"
                        "Ihre Organisation blockiert Service Account Keys.\n"
                        "Nutzen Sie stattdessen Application Default Credentials:\n\n"
                        "1. Installieren Sie Google Cloud SDK:\n"
                        "   https://cloud.google.com/sdk/docs/install\n\n"
                        "2. Führen Sie in PowerShell aus:\n"
                        "   gcloud auth application-default login\n\n"
                        "3. Melden Sie sich in Ihrem Google-Account an\n\n"
                        "4. Wählen Sie in der App: Cloud Vision OHNE Credentials-Datei\n"
                        "   (lassen Sie das Feld leer)"
                    )
                else:
                    raise ValueError(f"Unbekannter Credential-Typ in der JSON-Datei")
            else:
                # Keine Credentials-Datei - versuche Application Default Credentials
                print("Initialisiere Google Cloud Vision API mit Application Default Credentials...")
                print("Falls ein Fehler auftritt, führen Sie aus: gcloud auth application-default login")
                try:
                    self.vision_client = vision.ImageAnnotatorClient()
                except Exception as e:
                    raise ValueError(
                        f"Konnte nicht mit Default Credentials verbinden.\n\n"
                        f"Fehler: {str(e)}\n\n"
                        f"Bitte installieren Sie Google Cloud SDK und führen Sie aus:\n"
                        f"  gcloud auth application-default login\n\n"
                        f"Download: https://cloud.google.com/sdk/docs/install"
                    )
    
    def _check_credential_type(self, credentials_path: str) -> str:
        """
        Prüft den Typ der Credential-Datei.
        
        Returns:
            'service_account' oder 'oauth2_client'
        """
        try:
            with open(credentials_path, 'r') as f:
                cred_data = json.load(f)
            
            if 'type' in cred_data and cred_data['type'] == 'service_account':
                return 'service_account'
            elif 'installed' in cred_data or 'web' in cred_data:
                return 'oauth2_client'
            else:
                return 'unknown'
        except Exception:
            return 'unknown'
    
    def preprocess_image(self, image: Image.Image) -> Image.Image:
        """
        Verbessert das Bild für bessere OCR-Erkennung.
        
        Args:
            image: PIL Image Objekt
            
        Returns:
            Vorverarbeitetes Bild
        """
        # In Graustufen konvertieren
        if image.mode != 'L':
            image = image.convert('L')
        
        # Kontrast erhöhen
        enhancer = ImageEnhance.Contrast(image)
        image = enhancer.enhance(2.0)
        
        # Schärfe erhöhen
        enhancer = ImageEnhance.Sharpness(image)
        image = enhancer.enhance(1.5)
        
        # Rauschen reduzieren
        image = image.filter(ImageFilter.MedianFilter(size=3))
        
        # Schwellenwert anwenden (Binarisierung)
        # Adaptive Schwellenwertbildung für bessere Ergebnisse bei unterschiedlicher Beleuchtung
        threshold = 128
        image = image.point(lambda p: 255 if p > threshold else 0)
        
        return image
    
    def recognize_text(self, image_path: Path, use_preprocessing: Optional[bool] = None, 
                      apply_postprocessing: bool = True) -> str:
        """
        Erkennt Text aus einem Karteikartenimage.
        
        Args:
            image_path: Pfad zum Bild
            use_preprocessing: Überschreibt die Standard-Vorverarbeitung
            apply_postprocessing: Wenn True, wird Text-Nachbearbeitung angewendet
            
        Returns:
            Erkannter Text als String
        """
        try:
            # Vorverarbeitung anwenden falls aktiviert
            if use_preprocessing is None:
                use_preprocessing = self.preprocess
            
            # OCR durchführen
            if self.ocr_method == 'easyocr':
                text = self._recognize_with_easyocr(image_path, use_preprocessing)
            elif self.ocr_method == 'cloud_vision':
                text = self._recognize_with_cloud_vision(image_path, use_preprocessing)
            else:
                text = self._recognize_with_tesseract(image_path, use_preprocessing)
            
            # WICHTIG: Post-Processing immer anwenden wenn gewünscht UND Post-Processor existiert
            if apply_postprocessing and self.postprocessor:
                print(f"[DEBUG] Text VOR Post-Processing (Länge: {len(text)}): {text[:100]}...")
                text = self.postprocessor.process(text, aggressive=False)
                print(f"[DEBUG] Text NACH Post-Processing (Länge: {len(text)}): {text[:100]}...")
            else:
                print(f"[DEBUG] Post-Processing übersprungen: apply={apply_postprocessing}, processor={self.postprocessor is not None}")
            
            return text
        except Exception as e:
            return f"Fehler bei der Texterkennung: {str(e)}"
    
    def _recognize_with_easyocr(self, image_path: Path, use_preprocessing: bool) -> str:
        """Nutzt EasyOCR für die Erkennung."""
        if self.reader is None:
            return "EasyOCR wurde nicht initialisiert"
        
        if use_preprocessing:
            # Lade und verarbeite das Bild
            image = Image.open(image_path)
            processed_image = self.preprocess_image(image)
            
            # Konvertiere zu numpy array für EasyOCR
            img_array = np.array(processed_image)
            
            # EasyOCR mit vorverarbeitetem Bild
            results = self.reader.readtext(img_array, detail=0, paragraph=True)
        else:
            # Direkt ohne Vorverarbeitung
            results = self.reader.readtext(str(image_path), detail=0, paragraph=True)
        
        # Kombiniere alle erkannten Textzeilen
        text = '\n'.join(results)
        return text if text else "Kein Text erkannt"
    
    def _recognize_with_tesseract(self, image_path: Path, use_preprocessing: bool) -> str:
        """Nutzt Tesseract OCR für die Erkennung."""
        # Öffne das Bild
        image = Image.open(image_path)
        
        if use_preprocessing:
            image = self.preprocess_image(image)
        
        # Nutze Tesseract mit deutscher Sprache
        # Für Handschrift: Parameter können angepasst werden
        custom_config = r'--oem 3 --psm 6 -l deu'
        text = pytesseract.image_to_string(image, config=custom_config)
        
        return text.strip() if text.strip() else "Kein Text erkannt"
    
    def _recognize_with_cloud_vision(self, image_path: Path, use_preprocessing: bool) -> str:
        """Nutzt Google Cloud Vision API für die Erkennung."""
        if self.vision_client is None:
            return "Google Cloud Vision wurde nicht initialisiert"
        
        # Lade Bild
        image = Image.open(image_path)
        
        if use_preprocessing:
            image = self.preprocess_image(image)
        
        # Konvertiere zu Bytes für Cloud Vision
        import io
        img_byte_arr = io.BytesIO()
        image.save(img_byte_arr, format='PNG')
        content = img_byte_arr.getvalue()
        
        # Erstelle Vision API Image
        vision_image = vision.Image(content=content)
        
        # Führe Handschrifterkennung aus
        # document_text_detection ist optimiert für dichte Textdokumente
        response = self.vision_client.document_text_detection(image=vision_image)
        
        if response.error.message:
            return f"Cloud Vision Fehler: {response.error.message}"
        
        # Extrahiere erkannten Text
        if response.full_text_annotation:
            text = response.full_text_annotation.text
            return text.strip() if text.strip() else "Kein Text erkannt"
        else:
            return "Kein Text erkannt"
