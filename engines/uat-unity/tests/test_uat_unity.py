import os
import struct
import sys
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request
import zipfile
from types import SimpleNamespace
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import uat_unity as uat


def write_pe(path, machine):
    data = bytearray(256)
    data[0:2] = b'MZ'
    struct.pack_into('<I', data, 0x3C, 128)
    data[128:132] = b'PE\x00\x00'
    struct.pack_into('<H', data, 132, machine)
    with open(path, 'wb') as f:
        f.write(data)


class DetectionTests(unittest.TestCase):
    def setUp(self):
        self.old_game_dir = uat.GAME_DIR
        self.temp = tempfile.TemporaryDirectory()
        uat.GAME_DIR = self.temp.name

    def tearDown(self):
        uat.GAME_DIR = self.old_game_dir
        self.temp.cleanup()

    def make_data(self):
        data_dir = os.path.join(self.temp.name, 'Sample_Data')
        os.makedirs(data_dir)
        return data_dir

    def test_detects_mono_x64(self):
        write_pe(os.path.join(self.temp.name, 'Sample.exe'), 0x8664)
        data_dir = self.make_data()
        os.makedirs(os.path.join(data_dir, 'Managed'))
        open(os.path.join(data_dir, 'Managed', 'Assembly-CSharp.dll'), 'wb').close()
        os.makedirs(os.path.join(self.temp.name, 'MonoBleedingEdge'))
        info = uat.detect_game()
        self.assertTrue(info['valid'])
        self.assertEqual(info['runtime'], 'Mono')
        self.assertEqual(info['architecture'], 'x64')

    def test_detects_il2cpp_x86(self):
        write_pe(os.path.join(self.temp.name, 'Sample.exe'), 0x014C)
        write_pe(os.path.join(self.temp.name, 'GameAssembly.dll'), 0x014C)
        data_dir = self.make_data()
        metadata = os.path.join(data_dir, 'il2cpp_data', 'Metadata')
        os.makedirs(metadata)
        open(os.path.join(metadata, 'global-metadata.dat'), 'wb').close()
        info = uat.detect_game()
        self.assertTrue(info['valid'])
        self.assertEqual(info['runtime'], 'IL2CPP')
        self.assertEqual(info['architecture'], 'x86')

    def test_unknown_runtime_is_not_assumed_mono(self):
        write_pe(os.path.join(self.temp.name, 'Sample.exe'), 0x8664)
        self.make_data()
        info = uat.detect_game()
        self.assertEqual(info['runtime'], 'Unknown')


class SafetyTests(unittest.TestCase):
    def test_existing_bepinex_is_preserved_when_only_xunity_is_missing(self):
        old_game_dir, old_state, old_config, old_cache = uat.GAME_DIR, uat.UAT_DIR, uat.CONFIG_PATH, uat.CACHE_ZIP_DIR
        try:
            with tempfile.TemporaryDirectory() as temp:
                game, state = os.path.join(temp, 'game'), os.path.join(temp, 'state')
                os.makedirs(game)
                os.makedirs(state)
                uat.GAME_DIR, uat.UAT_DIR = game, state
                uat.CONFIG_PATH = os.path.join(state, 'unity_uat_config.json')
                uat.CACHE_ZIP_DIR = os.path.join(state, '_cache_downloads')
                os.makedirs(uat.CACHE_ZIP_DIR)
                write_pe(os.path.join(game, 'Sample.exe'), 0x8664)
                managed = os.path.join(game, 'Sample_Data', 'Managed')
                os.makedirs(managed)
                open(os.path.join(managed, 'Assembly-CSharp.dll'), 'wb').close()
                core = os.path.join(game, 'BepInEx', 'core')
                os.makedirs(core)
                existing = os.path.join(core, 'BepInEx.dll')
                with open(existing, 'wb') as file:
                    file.write(b'preinstalled-mod-loader')
                requested = []

                def fake_download(url, destination, *_args):
                    requested.append(os.path.basename(url))
                    with zipfile.ZipFile(destination, 'w') as archive:
                        archive.writestr('BepInEx/core/XUnity.Common.dll', b'xunity-common')
                        archive.writestr('BepInEx/plugins/XUnity.AutoTranslator/XUnity.AutoTranslator.Plugin.Core.dll', b'plugin-core')
                        archive.writestr('BepInEx/plugins/XUnity.AutoTranslator/XUnity.AutoTranslator.Plugin.BepInEx.dll', b'plugin-mono')
                        archive.writestr('BepInEx/plugins/XUnity.AutoTranslator/Translators/CustomTranslate.dll', b'custom')
                        archive.writestr('BepInEx/plugins/XUnity.ResourceRedirector/XUnity.ResourceRedirector.BepInEx.dll', b'redirector')
                    return destination

                with patch.object(uat, 'download_file', side_effect=fake_download):
                    self.assertTrue(uat.install_bepinex_xunity())
                self.assertEqual(len(requested), 1)
                self.assertIn('AutoTranslator', requested[0])
                with open(existing, 'rb') as file:
                    self.assertEqual(file.read(), b'preinstalled-mod-loader')
                self.assertEqual(uat.installation_status()['xunity_runtime'], 'Mono')
        finally:
            uat.GAME_DIR, uat.UAT_DIR, uat.CONFIG_PATH, uat.CACHE_ZIP_DIR = old_game_dir, old_state, old_config, old_cache

    def test_partial_bepinex_is_not_overwritten(self):
        old_game_dir = uat.GAME_DIR
        try:
            with tempfile.TemporaryDirectory() as game:
                uat.GAME_DIR = game
                write_pe(os.path.join(game, 'Sample.exe'), 0x8664)
                managed = os.path.join(game, 'Sample_Data', 'Managed')
                os.makedirs(managed)
                open(os.path.join(managed, 'Assembly-CSharp.dll'), 'wb').close()
                os.makedirs(os.path.join(game, 'BepInEx', 'core'))
                with patch.object(uat, 'download_file') as download:
                    with self.assertRaisesRegex(RuntimeError, 'incompleto'):
                        uat.install_bepinex_xunity()
                    download.assert_not_called()
        finally:
            uat.GAME_DIR = old_game_dir

    def test_existing_wrong_xunity_variant_is_not_replaced(self):
        old_game_dir = uat.GAME_DIR
        try:
            with tempfile.TemporaryDirectory() as game:
                uat.GAME_DIR = game
                write_pe(os.path.join(game, 'Sample.exe'), 0x8664)
                managed = os.path.join(game, 'Sample_Data', 'Managed')
                os.makedirs(managed)
                open(os.path.join(managed, 'Assembly-CSharp.dll'), 'wb').close()
                core = os.path.join(game, 'BepInEx', 'core')
                plugin = os.path.join(game, 'BepInEx', 'plugins', 'XUnity.AutoTranslator')
                redirector = os.path.join(game, 'BepInEx', 'plugins', 'XUnity.ResourceRedirector')
                os.makedirs(core)
                os.makedirs(plugin)
                os.makedirs(redirector)
                for path in (os.path.join(core, 'BepInEx.dll'), os.path.join(core, 'XUnity.Common.dll'),
                             os.path.join(plugin, 'XUnity.AutoTranslator.Plugin.Core.dll'),
                             os.path.join(plugin, 'XUnity.AutoTranslator.Plugin.BepInEx-IL2CPP.dll'),
                             os.path.join(plugin, 'Translators', 'CustomTranslate.dll'),
                             os.path.join(redirector, 'XUnity.ResourceRedirector.BepInEx-IL2CPP.dll')):
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    with open(path, 'wb') as file:
                        file.write(b'existing')
                with patch.object(uat, 'download_file') as download:
                    with self.assertRaisesRegex(RuntimeError, 'XUnity IL2CPP'):
                        uat.install_bepinex_xunity()
                    download.assert_not_called()
        finally:
            uat.GAME_DIR = old_game_dir

    def test_existing_bepinex_six_mono_is_not_treated_as_compatible_five(self):
        old_game_dir = uat.GAME_DIR
        try:
            with tempfile.TemporaryDirectory() as game:
                uat.GAME_DIR = game
                write_pe(os.path.join(game, 'Sample.exe'), 0x8664)
                managed = os.path.join(game, 'Sample_Data', 'Managed')
                os.makedirs(managed)
                open(os.path.join(managed, 'Assembly-CSharp.dll'), 'wb').close()
                core = os.path.join(game, 'BepInEx', 'core')
                os.makedirs(core)
                open(os.path.join(core, 'BepInEx.Unity.Mono.dll'), 'wb').close()
                with patch.object(uat, 'download_file') as download:
                    with self.assertRaisesRegex(RuntimeError, 'requer BepInEx 5'):
                        uat.install_bepinex_xunity()
                    download.assert_not_called()
        finally:
            uat.GAME_DIR = old_game_dir

    def test_preflight_rejects_conflict_without_writing_other_files(self):
        with tempfile.TemporaryDirectory() as temp:
            stage, game = os.path.join(temp, 'stage'), os.path.join(temp, 'game')
            os.makedirs(os.path.join(stage, 'BepInEx', 'core'))
            os.makedirs(os.path.join(game, 'BepInEx', 'core'))
            existing = os.path.join(game, 'BepInEx', 'core', 'XUnity.Common.dll')
            with open(existing, 'wb') as file:
                file.write(b'other-version')
            with open(os.path.join(stage, 'BepInEx', 'core', 'XUnity.Common.dll'), 'wb') as file:
                file.write(b'new-version')
            with open(os.path.join(stage, 'new-file.txt'), 'wb') as file:
                file.write(b'new')
            with self.assertRaisesRegex(RuntimeError, 'existente diferente'):
                uat._copy_missing_only([stage], game)
            self.assertFalse(os.path.exists(os.path.join(game, 'new-file.txt')))
            with open(existing, 'rb') as file:
                self.assertEqual(file.read(), b'other-version')

    def test_failed_copy_removes_only_new_files_and_directories(self):
        with tempfile.TemporaryDirectory() as temp:
            stage, game = os.path.join(temp, 'stage'), os.path.join(temp, 'game')
            os.makedirs(os.path.join(stage, 'BepInEx', 'plugins'))
            os.makedirs(game)
            source = os.path.join(stage, 'BepInEx', 'plugins', 'plugin.dll')
            with open(source, 'wb') as file:
                file.write(b'new')

            def fail_after_create(_source, target):
                with open(target, 'wb') as file:
                    file.write(b'partial')
                raise OSError('disk full')

            with patch.object(uat.shutil, 'copy2', side_effect=fail_after_create):
                with self.assertRaisesRegex(OSError, 'disk full'):
                    uat._copy_missing_only([stage], game)
            self.assertFalse(os.path.exists(os.path.join(game, 'BepInEx')))

    def test_numbered_language_selector_and_cancel(self):
        options = [('en', 'English'), ('pb', 'Portugues (Brasil)')]
        with patch('builtins.input', return_value='2'):
            self.assertEqual(uat._choose_language_numbered('Idioma', options, 'en'), 'pb')
        with patch('builtins.input', return_value='0'):
            self.assertIsNone(uat._choose_language_numbered('Idioma', options, 'en'))

    def test_model_metadata_alone_is_not_installed(self):
        with tempfile.TemporaryDirectory() as temp:
            pkg = SimpleNamespace(package_path=temp)
            with open(os.path.join(temp, 'metadata.json'), 'w') as f:
                f.write('{}')
            self.assertFalse(uat._package_complete(pkg))
            os.makedirs(os.path.join(temp, 'model'))
            for relative in ('sentencepiece.model', 'model/model.bin', 'model/config.json'):
                with open(os.path.join(temp, *relative.split('/')), 'wb') as f:
                    f.write(b'x')
            self.assertTrue(uat._package_complete(pkg))

    def test_old_argos_model_without_config_is_accepted(self):
        with tempfile.TemporaryDirectory() as temp:
            pkg = SimpleNamespace(package_path=temp)
            os.makedirs(os.path.join(temp, 'model'))
            for relative in ('metadata.json', 'sentencepiece.model', 'model/model.bin'):
                with open(os.path.join(temp, *relative.split('/')), 'wb') as f:
                    f.write(b'x')
            self.assertTrue(uat._package_complete(pkg))

    def test_argos_model_may_use_bpe_tokenizer(self):
        with tempfile.TemporaryDirectory() as temp:
            pkg = SimpleNamespace(package_path=temp)
            os.makedirs(os.path.join(temp, 'model'))
            for relative in ('metadata.json', 'bpe.model', 'model/model.bin'):
                with open(os.path.join(temp, *relative.split('/')), 'wb') as f:
                    f.write(b'x')
            self.assertTrue(uat._package_complete(pkg))

    def test_xunity_detection_treats_brackets_literally(self):
        old_game_dir = uat.GAME_DIR
        try:
            with tempfile.TemporaryDirectory() as temp:
                game = os.path.join(temp, '[Ryuugames] Sample')
                plugin = os.path.join(game, 'BepInEx', 'plugins', 'XUnity.AutoTranslator')
                os.makedirs(plugin)
                dll = os.path.join(plugin, 'XUnity.AutoTranslator.Plugin.Core.dll')
                open(dll, 'wb').close()
                uat.GAME_DIR = game
                self.assertEqual(uat._xunity_dlls(), [dll])
        finally:
            uat.GAME_DIR = old_game_dir

    def test_rejects_zip_path_traversal(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = os.path.join(temp, 'bad.zip')
            destination = os.path.join(temp, 'out')
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr('../escape.txt', 'no')
            with self.assertRaises(RuntimeError):
                uat._extract_safe(archive, destination)

    def test_ini_updates_existing_keys(self):
        original = '[General]\nLanguage=en\nFromLanguage=ja\n'
        changed = uat._set_ini(original, 'General', 'Language', 'pt-BR')
        self.assertIn('Language=pt-BR', changed)
        self.assertNotIn('Language=en', changed)

    def test_ini_adds_missing_key_inside_existing_section(self):
        original = '[General]\nLanguage=en\n[Service]\nEndpoint=GoogleTranslate\n'
        changed = uat._set_ini(original, 'General', 'FromLanguage', 'ja')
        self.assertEqual(changed.count('[General]'), 1)
        self.assertLess(changed.index('FromLanguage=ja'), changed.index('[Service]'))

    def test_existing_xunity_config_is_backed_up_before_edit(self):
        old_game_dir, old_state = uat.GAME_DIR, uat.UAT_DIR
        try:
            with tempfile.TemporaryDirectory() as temp:
                uat.GAME_DIR = os.path.join(temp, 'game')
                uat.UAT_DIR = os.path.join(temp, 'state')
                config = os.path.join(uat.GAME_DIR, 'BepInEx', 'config')
                os.makedirs(config)
                ini = os.path.join(config, 'AutoTranslatorConfig.ini')
                original = '[General]\nLanguage=en\n[Service]\nEndpoint=GoogleTranslate\n'
                with open(ini, 'w', encoding='utf-8') as file:
                    file.write(original)
                uat.patch_autotranslator_ini('ja', 'pb')
                backups = os.listdir(os.path.join(uat.UAT_DIR, 'Backups'))
                self.assertEqual(len(backups), 1)
                with open(os.path.join(uat.UAT_DIR, 'Backups', backups[0]), encoding='utf-8') as file:
                    self.assertEqual(file.read(), original)
                with open(ini, encoding='utf-8') as file:
                    updated = file.read()
                self.assertEqual(updated.count('[General]'), 1)
                self.assertIn('FromLanguage=ja', updated)
        finally:
            uat.GAME_DIR, uat.UAT_DIR = old_game_dir, old_state

    @unittest.skipUnless(os.name == 'nt', 'junction de compatibilidade exclusiva do Windows')
    def test_unicode_model_path_gets_ascii_alias(self):
        with tempfile.TemporaryDirectory() as temp:
            portable = os.path.join(temp, 'modelos-japones-日本語')
            os.makedirs(portable)
            with patch.dict(os.environ, {'LOCALAPPDATA': temp}):
                alias = uat._runtime_models_dir(portable)
            self.assertTrue(uat._is_ascii_path(alias))
            self.assertTrue(os.path.samefile(alias, portable))

    def test_detects_japanese_text_without_guessing_from_latin_words(self):
        code, confidence = uat._detect_text_language(
            'はじめから つづきから 設定 ゲームを終了する', {'en', 'ja'})
        self.assertEqual(code, 'ja')
        self.assertGreaterEqual(confidence, 0.8)

    def test_displayed_xunity_text_has_priority(self):
        old_game_dir = uat.GAME_DIR
        try:
            with tempfile.TemporaryDirectory() as game:
                uat.GAME_DIR = game
                cache = os.path.join(game, 'BepInEx', 'Translation', 'pt-BR', 'Text')
                os.makedirs(cache)
                with open(os.path.join(cache, '_AutoGeneratedTranslations.txt'), 'w', encoding='utf-8') as f:
                    f.write('Start a new game=Comecar um novo jogo\n')
                    f.write('Continue from your last save=Continuar do ultimo salvamento\n')
                    f.write('Open the settings menu=Abrir as configuracoes\n')
                detected = uat.detect_game_language({'en', 'ja'})
                self.assertEqual(detected['code'], 'en')
                self.assertIn('XUnity', detected['evidence'])
        finally:
            uat.GAME_DIR = old_game_dir

    def test_explicit_game_language_wins_over_cached_text(self):
        old_game_dir = uat.GAME_DIR
        try:
            with tempfile.TemporaryDirectory() as game:
                uat.GAME_DIR = game
                settings = os.path.join(game, 'Game_Data', 'StreamingAssets')
                os.makedirs(settings)
                with open(os.path.join(settings, 'settings.json'), 'w', encoding='utf-8') as f:
                    f.write('{"language": "ja", "source_language": "en"}')
                detected = uat.detect_game_language({'en', 'ja'})
                self.assertEqual(detected['code'], 'ja')
                self.assertEqual(detected['confidence'], 0.98)
        finally:
            uat.GAME_DIR = old_game_dir

    def test_ini_uses_translate_endpoint(self):
        old_game_dir = uat.GAME_DIR
        try:
            with tempfile.TemporaryDirectory() as game:
                uat.GAME_DIR = game
                with patch.object(uat, 'server_port', return_value=54321):
                    ini = uat.patch_autotranslator_ini('en', 'pb')
                with open(ini, 'r', encoding='utf-8') as f:
                    content = f.read()
                self.assertIn('Url=http://127.0.0.1:54321/translate', content)
        finally:
            uat.GAME_DIR = old_game_dir

    def test_legacy_root_url_translates_instead_of_returning_ok(self):
        server = uat._Srv(('127.0.0.1', 0), uat._Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            query = urllib.parse.urlencode({'text': 'Hello', 'from': 'en', 'to': 'pb'})
            url = 'http://127.0.0.1:{}/?{}'.format(server.server_port, query)
            with patch.object(uat, 'translate_text', return_value='Ola'):
                with urllib.request.urlopen(url, timeout=2) as response:
                    self.assertEqual(response.read().decode('utf-8'), 'Ola')
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_chain_translates_two_pairs_in_one_runtime(self):
        config = {'source_language': 'ja', 'target_language': 'pt-BR',
                  'flow_mode': 'chain', 'intermediate_language': 'en'}
        with patch.object(uat, 'load_config', return_value=config), \
             patch.object(uat, '_translate_pair', side_effect=[(True, 'Hello'), (True, 'Olá')]) as translate:
            self.assertEqual(uat.translate_text('こんにちは', 'auto', 'pb'), 'Olá')
        self.assertEqual(translate.call_args_list[0].args[1:], ('ja', 'en'))
        self.assertEqual(translate.call_args_list[1].args[1:], ('en', 'pb'))

    def test_chain_never_returns_intermediate_text_when_second_step_fails(self):
        config = {'source_language': 'ja', 'target_language': 'pt-BR',
                  'flow_mode': 'chain', 'intermediate_language': 'en'}
        with patch.object(uat, 'load_config', return_value=config), \
             patch.object(uat, '_translate_pair', side_effect=[(True, 'Hello'), (False, 'Hello')]):
            self.assertEqual(uat.translate_text('こんにちは', 'auto', 'pb'), 'こんにちは')

    def test_translation_normalizes_combining_accents(self):
        config = {'flow_mode': 'direct'}
        with patch.object(uat, 'load_config', return_value=config), \
             patch.object(uat, '_translate_pair', return_value=(True, 'ac\u0327a\u0303o')) as translate:
            self.assertEqual(uat.translate_text('Cafe\u0301', 'en', 'pb'), 'ação')
        self.assertEqual(translate.call_args.args[0], 'Café')

    def test_emoji_survives_direct_translation(self):
        config = {'flow_mode': 'direct'}
        with patch.object(uat, 'load_config', return_value=config), \
             patch.object(uat, '_translate_pair', return_value=(True, 'Olá UATEMOJI0!')):
            self.assertEqual(uat.translate_text('Hello 👋!', 'en', 'pb'), 'Olá 👋!')

    def test_emoji_survives_when_model_drops_placeholder(self):
        config = {'flow_mode': 'direct'}
        def model(text, source, target):
            return True, 'Olá!' if 'UATEMOJI' in text else text.replace('Hello', 'Olá')
        with patch.object(uat, 'load_config', return_value=config), \
             patch.object(uat, '_translate_pair', side_effect=model):
            result = uat.translate_text('Hello 👩‍👩‍👧‍👦!', 'en', 'pb')
        self.assertIn('👩‍👩‍👧‍👦', result)
        self.assertIn('Olá', result)

    def test_emoji_fallback_keeps_spacing(self):
        def model(text):
            if 'UATEMOJI' in text:
                return True, 'Olá amigo!'
            return True, {'Hello': 'Olá', 'friend!': 'amigo!'}.get(text, text)
        self.assertEqual(
            uat._translate_preserving_emoji('Hello 👋 friend!', model),
            (True, 'Olá 👋 amigo!'))

    def test_emoji_only_skips_model(self):
        with patch.object(uat, 'load_config', return_value={'flow_mode': 'direct'}), \
             patch.object(uat, '_translate_pair') as translate:
            self.assertEqual(uat.translate_text('👋', 'en', 'pb'), '👋')
        translate.assert_not_called()

    def test_emoji_marker_does_not_replace_literal_game_text(self):
        config = {'flow_mode': 'direct'}
        with patch.object(uat, 'load_config', return_value=config), \
             patch.object(uat, '_translate_pair', side_effect=lambda text, *_: (True, text)):
            self.assertEqual(uat.translate_text('UATEMOJI0 👋', 'en', 'pb'), 'UATEMOJI0 👋')


@unittest.skipUnless(os.environ.get('UAT_LIVE_TEST') == '1',
                     'defina UAT_LIVE_TEST=1 para testar os ZIPs oficiais')
class LiveInstallTests(unittest.TestCase):
    def test_official_mono_and_il2cpp_packages(self):
        old_game_dir, old_state, old_config, old_cache = uat.GAME_DIR, uat.UAT_DIR, uat.CONFIG_PATH, uat.CACHE_ZIP_DIR
        try:
            variants = (
                ('Mono', 'x64', 0x8664), ('Mono', 'x86', 0x014C),
                ('IL2CPP', 'x64', 0x8664), ('IL2CPP', 'x86', 0x014C),
            )
            for runtime, architecture, machine in variants:
                with self.subTest(runtime=runtime, architecture=architecture), tempfile.TemporaryDirectory() as game:
                    uat.GAME_DIR = game
                    uat.UAT_DIR = os.path.join(game, 'sftranslator-state')
                    uat.CONFIG_PATH = os.path.join(uat.UAT_DIR, 'unity_uat_config.json')
                    uat.CACHE_ZIP_DIR = os.path.join(uat.UAT_DIR, '_cache_downloads')
                    os.makedirs(uat.CACHE_ZIP_DIR)
                    write_pe(os.path.join(game, 'Sample.exe'), machine)
                    data_dir = os.path.join(game, 'Sample_Data')
                    os.makedirs(data_dir)
                    if runtime == 'Mono':
                        os.makedirs(os.path.join(data_dir, 'Managed'))
                        open(os.path.join(data_dir, 'Managed', 'Assembly-CSharp.dll'), 'wb').close()
                        os.makedirs(os.path.join(game, 'MonoBleedingEdge'))
                    else:
                        write_pe(os.path.join(game, 'GameAssembly.dll'), machine)
                        metadata = os.path.join(data_dir, 'il2cpp_data', 'Metadata')
                        os.makedirs(metadata)
                        open(os.path.join(metadata, 'global-metadata.dat'), 'wb').close()
                    self.assertTrue(uat.install_bepinex_xunity())
                    status = uat.installation_status()
                    self.assertEqual(status['bepinex_runtime'], runtime)
                    self.assertTrue(status['xunity'])
                    self.assertTrue(status['runtime_match'])
        finally:
            uat.GAME_DIR, uat.UAT_DIR, uat.CONFIG_PATH, uat.CACHE_ZIP_DIR = old_game_dir, old_state, old_config, old_cache


if __name__ == '__main__':
    unittest.main()
