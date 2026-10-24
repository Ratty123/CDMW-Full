"""The experimental workflow and limits reach both manuals in every locale."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import re

import pytest
from PySide6.QtWidgets import QApplication

from cdmw.domain.localization import BUILTIN_LANGUAGES
from cdmw.ui.localization import UiLocalizer
from cdmw.ui.localization_catalogs_v2 import load_builtin_catalog
from cdmw.ui.shell.about_documentation_en import CREATE_NEW_ITEM_SECTION
from cdmw.ui.shell.help_dialogs import AboutDialog
from scripts.export_github_wiki import build_pages, page_slug


@pytest.fixture(scope='module')
def wiki():
    return build_pages()


@pytest.mark.parametrize('language', BUILTIN_LANGUAGES, ids=lambda language: language.code)
def test_v3_help_and_wiki_keep_localized_workflow_and_proof_limits(tmp_path, language, wiki):
    app = QApplication.instance() or QApplication([])
    keys = [text for text in re.findall(r'<p>(.*?)</p>', CREATE_NEW_ITEM_SECTION['html'], re.S)
            if any(marker in text for marker in ('DMM V3 field JSON', 'Only existing models and icons',
                                                 'Enable the DMM package'))]
    assert len(keys) == 3
    catalog = load_builtin_catalog(language.code)['translations']
    dialog = AboutDialog(None, title='Documentation', intro_html='', sections=[CREATE_NEW_ITEM_SECTION])
    localizer = UiLocalizer(language_dir=tmp_path / language.code, language_code=language.code)
    try:
        dialog.select_section('new_item_studio')
        localizer.apply(dialog)
        displayed = dialog.browser.toPlainText()
        manual = wiki[page_slug('Create-New-Item', language.code) + '.md'].replace('**', '').replace('`', '')
        manual = ' '.join(manual.split())
        for key in keys:
            translated = catalog[key]
            assert translated in displayed
            assert ' '.join(translated.split()) in manual
            assert language.code == 'en' or translated != key
        for key in ('DMM V3 field JSON (experimental)',
            'Export retained independent items using existing models and icons. Unsupported changes refuse. Keep the included .cditem source; DMM mounting and game behaviour remain unverified.'):
            assert key in catalog and (language.code == 'en' or catalog[key] != key)
    finally:
        localizer.shutdown()
        dialog.deleteLater()
        app.processEvents()
