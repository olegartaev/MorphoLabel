"""A single Native + Detail action, safe warm starts and schema-neutral calibration."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from app.native_structure_bootstrap import choose_detail_channels,initialize_parent
from app.xray_structures_ui import XRayStructureWorkspace
from ai_runtime.universal_multires import pipeline_components


class NativeOnlyWorkflowTests(unittest.TestCase):
    def test_train_always_routes_to_native_detail_even_for_a_legacy_initializer(self):
        for parent in ('ImageNet ResNet18','old_model','native_model'):
            workspace=object.__new__(XRayStructureWorkspace);workspace._busy=False
            workspace.training_parent_choice=SimpleNamespace(get=lambda:parent)
            with patch.object(workspace,'train_highres_structure_ai') as train:
                workspace.train_structure_ai()
            train.assert_called_once_with()

    def test_calibration_is_schema_neutral_and_ties_keep_native(self):
        counts={'arbitrary_object':{'native':[4,0,3],'detail':[7,0,0]},
                'another_point':{'native':[7,0,0],'detail':[7,1,0]},
                'equal':{'native':[4,0,0],'detail':[4,0,0]},
                'unobserved':{'native':[0,0,0],'detail':[0,0,0]}}
        self.assertEqual(choose_detail_channels(counts),['arbitrary_object'])

    def test_legacy_weights_only_initialize_two_distinct_components(self):
        from hashlib import sha256
        import zipfile
        source={'model_id':'old','backend':'resnet18_heatmap_v1'}
        raw=b'checkpoint';meta={'input_size':[768,256],'structures':[{'id':'arbitrary_object'}]}
        def export(project,path,model_id):
            with zipfile.ZipFile(path,'w') as z:
                names=['artifacts/model.pth','artifacts/model.json']
                z.writestr('manifest.json',json.dumps({'files':dict.fromkeys(names,'unused')}))
                z.writestr(names[0],raw);z.writestr(names[1],json.dumps(meta))
        with tempfile.TemporaryDirectory() as scratch,patch('app.xray_structure_ai.export_structure_model_package',side_effect=export):
            _,metadata,data=initialize_parent(None,source,Path(scratch),seed=42,device='cpu')
        self.assertEqual(set(pipeline_components(metadata)),{'native','detail'})
        self.assertEqual(data['artifacts/native.pth'],raw)
        self.assertEqual(metadata['inference_pipeline']['native']['sha256'],sha256(raw).hexdigest())
        self.assertNotEqual(metadata['inference_pipeline']['native']['input_size'],metadata['inference_pipeline']['detail']['input_size'])

    def test_new_model_requires_verified_local_starter_without_network_fallback(self):
        with patch('app.ai_starters.local_starter',return_value=None),patch('app.xray_structure_ai.train_structure_model') as train:
            with self.assertRaisesRegex(RuntimeError,'Set up AI support'):
                initialize_parent(None,None,Path('.'),seed=42,device='cpu')
            train.assert_not_called()
