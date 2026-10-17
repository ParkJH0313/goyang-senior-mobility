"""Checkpoint invalidation, restoration and relocation under a Unicode path."""
import os,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
import numpy as np,pandas as pd
from src.analysis_io import ROOT,Context,inside,atomic_json,atomic_npz,parquet,sha
from src.artifact_cache import repair_derived,bind_input_caches,run_lock


class ExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        inside('.tmp').mkdir(parents=True,exist_ok=True)

    def test_concurrent_writer_blocked_and_lock_released(self):
        with tempfile.TemporaryDirectory(prefix='lock-test-',dir=inside('.tmp')) as temp:
            lock=Path(temp)/'run.lock'
            script="from src.artifact_cache import run_lock\nwith run_lock(__import__('sys').argv[1]): pass"
            with run_lock(lock):
                result=subprocess.run([sys.executable,'-X','utf8','-c',script,str(lock)],cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
                self.assertNotEqual(result.returncode,0)
                self.assertIn('Another analysis process',result.stderr)
            with run_lock(lock):pass

    def test_changed_inputs_invalidate_auxiliary_scope_cache(self):
        with tempfile.TemporaryDirectory(prefix='binding-test-',dir=inside('.tmp')) as temp:
            c=SimpleNamespace(cache=Path(temp),input_id='first-input')
            bind_input_caches(c)
            scope=c.cache/'scope_fixture.parquet';scope.write_bytes(b'fixture')
            untouched=c.cache/'routing_fixture.npz';untouched.write_bytes(b'signed separately')
            bind_input_caches(c);self.assertTrue(scope.exists())
            c.input_id='changed-origin-geometry';bind_input_caches(c)
            self.assertFalse(scope.exists());self.assertTrue(untouched.exists())

    def test_external_research_path_rejected(self):
        with self.assertRaises(ValueError):inside(ROOT.parent/'outside-study.bin')
        self.assertTrue(inside('outputs/not-created-yet/result.csv').is_relative_to(ROOT))

    def test_stage_resume_checks_content_and_configuration(self):
        with tempfile.TemporaryDirectory(prefix='stage-test-',dir=inside('.tmp')) as temp:
            c=Context.__new__(Context);c.output=Path(temp);c.config={'speed':.7};c.input_id='fixture-input';c.state={'stages':{}}
            calls=[]
            def calculate(ctx):
                calls.append(1);(ctx.step(1)/'result.txt').write_text('correct',encoding='utf-8');return {'count':1}
            module=SimpleNamespace(DEPENDENCIES=['src/analysis_io.py'],SETTINGS=['speed'],run=calculate)
            c.execute(1,module);c.execute(1,module);self.assertEqual(len(calls),1)
            c.config['speed']=.8;c.execute(1,module);self.assertEqual(len(calls),2)
            (c.step(1)/'result.txt').write_text('corrupt',encoding='utf-8');c.execute(1,module);self.assertEqual(len(calls),3)
            (c.step(1)/'result.txt').unlink();c.execute(1,module);self.assertEqual(len(calls),4)

    def test_private_checkpoint_loss_and_corruption_invalidate(self):
        with tempfile.TemporaryDirectory(prefix='cache-test-',dir=inside('.tmp')) as temp:
            c=Context.__new__(Context);c.output=Path(temp)/'output';c.cache=Path(temp)/'cache';c.run_id='fixture';c.output.mkdir();c.cache.mkdir()
            target=c.cache/'routing_fixture/origin_00000.npz'
            atomic_npz(target,od=np.array([[1.,np.inf]]));expected=sha(target);rel=target.relative_to(ROOT).as_posix()
            parquet(pd.DataFrame({'path':[rel]}),c.step(5)/'routing_checkpoint.parquet')
            atomic_json(c.step(5)/'completion.json',{'status':'complete'})
            atomic_json(c.cache/'checkpoints_fixture.json',{'files':{rel:expected}})
            repair_derived(c);self.assertTrue((c.step(5)/'completion.json').exists())
            target.write_bytes(b'corrupt');repair_derived(c)
            self.assertFalse(target.exists());self.assertFalse((c.step(5)/'completion.json').exists())
            atomic_json(c.step(5)/'completion.json',{'status':'complete'})
            repair_derived(c);self.assertFalse((c.step(5)/'completion.json').exists())

    def test_report_rejects_changed_calculation_code(self):
        from src.output_layout import CORE,STEPS,check_presentation_inputs
        paths=CORE+[f'steps/step{i:02d}_{name}.py' for i,name in enumerate(STEPS,1)]+['run.py','src/routing_runner.py']
        c=SimpleNamespace(inputs={'a':'hash'},state={'inputs':{'a':'hash'},'stages':{str(i):{'status':'complete','outputs':{}} for i in range(1,10)},'code_sha256':{p:sha(p) for p in paths}})
        check_presentation_inputs(c)
        c.state['code_sha256']['src/router.py']='different'
        with self.assertRaises(AssertionError):check_presentation_inputs(c)

    def test_portable_small_run_under_other_unicode_parent(self):
        with tempfile.TemporaryDirectory(prefix='휴대성 다른 부모-',dir=inside('.tmp')) as temp:
            root=Path(temp)/'이동한 연구 프로젝트';(root/'src').mkdir(parents=True);(root/'tests').mkdir()
            for name in ['analysis_io.py','router.py','walking.py','aggregation.py','timetable.py','path_diagnosis.py','spatial_network.py','preprocessing_common.py']:
                shutil.copy2(inside('src/'+name),root/'src'/name)
            for name in ['test_router.py','test_geometry.py']:shutil.copy2(inside('tests/'+name),root/'tests'/name)
            script="from src.analysis_io import initialize,ROOT; initialize(); from pathlib import Path; assert ROOT==Path.cwd(); import unittest; r=unittest.TextTestRunner(verbosity=0).run(unittest.defaultTestLoader.discover('tests')); raise SystemExit(not r.wasSuccessful())"
            result=subprocess.run([sys.executable,'-X','utf8','-c',script],cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=90)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__=='__main__':unittest.main()
