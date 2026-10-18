"""Match one inspected template against one fresh frame; never invent a screen.

This data-only adapter grants no launch, save, native-call or key authority. The
existing execution service and policy still guard every action and input scope.
"""
from copy import deepcopy
from io import BytesIO
import math

from cdmw.services import cditem_device_saves as saves
from cdmw.services.cditem_device_execution import _json, _snapshot_reference
from cdmw.services.cditem_device_runner import DeviceRunError, SCREENS
from cdmw.services.independent_item_package import digest

FORMAT = 'cdmw_cditem_frame_review_v1'
IMAGE_LIMIT = 64 * 1024 * 1024
PIXEL_LIMIT = 16_777_216


def _image(reference):
    from PIL import Image

    reference = _snapshot_reference(reference)
    path = saves._absolute(reference['path'])
    if path.stat().st_size > IMAGE_LIMIT:
        raise DeviceRunError('The reviewed frame exceeds its byte limit.')
    with path.open('rb') as reader:
        raw = reader.read(IMAGE_LIMIT + 1)
    if len(raw) > IMAGE_LIMIT or digest(raw) != reference['sha256']:
        raise DeviceRunError('The reviewed or captured frame changed.')
    with Image.open(BytesIO(raw)) as image:
        if image.format != 'PNG' or image.width * image.height > PIXEL_LIMIT:
            raise DeviceRunError('A bounded PNG game frame is required.')
        return image.convert('RGB')


class ReviewedFrameObserver:
    """At most one classification, derived from immutable inspected pixels."""

    def __init__(self, review_reference, execution_reference):
        import numpy as np

        self.reference = _snapshot_reference(review_reference)
        review = _json(self.reference)
        fields = {'format', 'execution', 'sequence', 'template', 'regions', 'max_mean_error',
                  'light_text', 'classification', 'inspection'}
        if not isinstance(review, dict) or set(review) != fields or review['format'] != FORMAT:
            raise DeviceRunError('Unsupported inspected frame review.')
        execution = _snapshot_reference(execution_reference)
        if _snapshot_reference(review['execution']) != execution:
            raise DeviceRunError('The inspected frame belongs to another execution.')
        self.sequence = review['sequence']
        if type(self.sequence) is not int or not 1 <= self.sequence <= 512:
            raise DeviceRunError('One exact next capture sequence is required.')
        # Check both immutable inputs before the execution can enter a scope.
        manifest = _json(execution)
        self.run_id = manifest.get('run_id') if isinstance(manifest, dict) else None
        if not isinstance(self.run_id, str) or not self.run_id:
            raise DeviceRunError('The reviewed execution has no run identity.')
        self.classification = deepcopy(review['classification'])
        observation_fields = {'screen', 'control', 'point', 'save_id', 'gameplay_witness', 'scenario', 'assertion'}
        if (not isinstance(self.classification, dict) or set(self.classification) != observation_fields
                or any(not isinstance(self.classification[key], str) or len(self.classification[key]) > 2048
                       for key in observation_fields - {'point'})
                or self.classification['screen'] not in SCREENS - {'unknown', 'modal'}):
            raise DeviceRunError('A bounded inspected screen classification is required.')
        point = self.classification['point']
        if point is not None and (not isinstance(point, list) or len(point) != 2
                                  or any(type(value) is not int for value in point)):
            raise DeviceRunError('Invalid inspected control point.')
        self.threshold = review['max_mean_error']
        if (type(self.threshold) not in (int, float) or not math.isfinite(self.threshold)
                or not 0 <= self.threshold <= 8 or type(review['light_text']) is not bool
                or not isinstance(review['inspection'], str) or not 0 < len(review['inspection'].strip()) <= 4096):
            raise DeviceRunError('An inspected explanation and bounded pixel tolerance are required.')
        image = _image(review['template'])
        self.size = image.size
        if point is not None and not (0 <= point[0] < image.width and 0 <= point[1] < image.height):
            raise DeviceRunError('The inspected control is outside the template.')
        self.regions = deepcopy(review['regions'])
        if not isinstance(self.regions, list) or not 1 <= len(self.regions) <= 8:
            raise DeviceRunError('One to eight inspected stable regions are required.')
        pixels = 0
        for box in self.regions:
            if (not isinstance(box, list) or len(box) != 4 or any(type(value) is not int for value in box)
                    or not 0 <= box[0] < box[2] <= image.width
                    or not 0 <= box[1] < box[3] <= image.height):
                raise DeviceRunError('An inspected region lies outside the template.')
            pixels += (box[2] - box[0]) * (box[3] - box[1])
        if pixels > 1_048_576:
            raise DeviceRunError('The inspected regions exceed their total pixel limit.')
        self.patches = [np.asarray(image.crop(box), dtype=np.int16) for box in self.regions]
        self.masks = None
        if review['light_text']:
            self.masks = [(patch.min(axis=2) > 170) & (patch.max(axis=2) - patch.min(axis=2) < 40)
                          for patch in self.patches]
            if any(int(mask.sum()) < 32 for mask in self.masks):
                raise DeviceRunError('Every inspected text region needs at least 32 stable light pixels.')
        self.used, self.matches = False, []

    def __call__(self, receipt):
        import numpy as np
        from cdmw.services.cditem_device_windows import _api

        if self.used:
            return None
        self.used = True
        if receipt['run_id'] != self.run_id:
            raise DeviceRunError('The fresh frame belongs to another reviewed run.')
        if receipt['sequence'] != self.sequence:
            raise DeviceRunError('The inspected frame review is stale or belongs to another capture sequence.')
        current = _image({'path': receipt['path'], 'sha256': receipt['sha256']})
        match = {'sequence': receipt['sequence'], 'same_dimensions': current.size == self.size,
                 'mean_absolute_errors': [], 'threshold': self.threshold, 'matched': False}
        self.matches.append(match)
        if current.size != self.size:
            return None
        differences = [np.abs(np.asarray(current.crop(box), dtype=np.int16) - patch)
                       for box, patch in zip(self.regions, self.patches)]
        errors = [float((difference if self.masks is None else difference[self.masks[index]]).mean())
                  for index, difference in enumerate(differences)]
        match['mean_absolute_errors'] = errors
        match['matched'] = all(error <= self.threshold for error in errors)
        if not match['matched']:
            return None
        value = deepcopy(self.classification)
        value['foreground'] = _api()[1].GetForegroundWindow() == receipt['window']['hwnd']
        return value

    def evidence(self):
        return {'format': FORMAT, 'review': dict(self.reference), 'matches': deepcopy(self.matches),
                'scope': 'One inspected baseline classification; native acceptance is not established.'}
