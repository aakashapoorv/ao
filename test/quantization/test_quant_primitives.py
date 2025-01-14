# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.

# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

# mypy: ignore-errors
# This test takes a long time to run
import unittest
import torch
from torchao.quantization.quant_primitives import (
    get_group_qparams_symmetric,
    quantize_affine,
    dequantize_affine,
    choose_qparams_affine,
    MappingType,
)

from torchao.quantization.utils import (
    TORCH_VERSION_AFTER_2_3,
    TORCH_VERSION_AFTER_2_4,
)

_SEED = 1234
torch.manual_seed(_SEED)

class TestQuantPrimitives(unittest.TestCase):
    SEED = 123

    @unittest.skipIf(not TORCH_VERSION_AFTER_2_3, "skipping when torch verion is 2.3 or lower")
    def test_get_group_qparams_symmetric(self):
        """
        Test that `get_group_qparams_symmetric` produces the exact same scales as
        `PerChannelMinMaxObserver._calculate_qparams`.
        """
        n_bit = 4
        qmin = -(2 ** (n_bit - 1))
        qmax = 2 ** (n_bit - 1) - 1
        eps = torch.finfo(torch.float32).eps
        groupsize = 256
        torch.manual_seed(self.SEED)
        weight = torch.randn(100, 256).to(torch.float16)

        # calculate observer scales
        obs = torch.ao.quantization.PerChannelMinMaxObserver(
            ch_axis=0,
            qscheme=torch.per_channel_symmetric,
            quant_min=qmin,
            quant_max=qmax,
            # This is needed to ensure `min_val` and `max_val` are fp16,
            # otherwise they default to fp32 and the qparams will be slightly off
            factory_kwargs={"dtype": torch.float16}
        )
        obs(weight)
        (scale_obs, _) = obs.calculate_qparams()
        scale_obs = scale_obs.reshape(weight.shape[0], -1)

        # assert that scales are identical
        (scale_ao, _) = get_group_qparams_symmetric(weight, n_bit, groupsize)
        torch.testing.assert_allclose(scale_obs, scale_ao, rtol=0, atol=0)

    def test_choose_qparams_group_sym(self):
        """Note: groupwise asymmetric quant is using a different way of computing zero_points, so
        we don't include it here. We may just replace it with per block quant
        """
        input = torch.randn(10, 10)
        mapping_type = MappingType.SYMMETRIC
        dtype = torch.int8
        block_size = (1, 2)
        scale, zero_point = choose_qparams_affine(input, mapping_type, block_size, dtype, eps=torch.finfo(torch.float32).eps)

        scale_ref, zp_ref = get_group_qparams_symmetric(input, n_bit=8, groupsize=2)

        self.assertTrue(torch.equal(scale, scale_ref))
        self.assertTrue(torch.equal(zero_point, zp_ref))

    @unittest.skipIf(not TORCH_VERSION_AFTER_2_3, "skipping when torch verion is 2.3 or lower")
    def test_choose_qparams_token_asym(self):
        input = torch.randn(10, 10)
        mapping_type = MappingType.ASYMMETRIC
        dtype = torch.int8
        block_size = (1, 10)
        scale, zero_point = choose_qparams_affine(input, mapping_type, block_size, dtype, eps=torch.finfo(torch.float32).eps)

        scale_ref, zp_ref = torch.ops.quantized_decomposed.choose_qparams_per_token_asymmetric(input, dtype)
        scale_ref = scale_ref.squeeze()
        zp_ref = zp_ref.squeeze()

        torch.testing.assert_allclose(scale, scale_ref, atol=10e-3, rtol=10e-3)
        self.assertTrue(torch.equal(zero_point, zp_ref))

    def test_choose_qparams_tensor_asym(self):
        input = torch.randn(10, 10)
        mapping_type = MappingType.ASYMMETRIC
        dtype = torch.int8
        block_size = (10, 10)
        eps = torch.finfo(torch.float32).eps
        scale, zero_point = choose_qparams_affine(input, mapping_type, block_size, dtype, eps=eps)


        quant_min = -128
        quant_max = 127
        scale_ref, zp_ref = torch.ops.quantized_decomposed.choose_qparams(input, quant_min, quant_max, eps, dtype)
        scale_ref = scale_ref.squeeze()
        zp_ref = zp_ref.squeeze()

        self.assertTrue(torch.equal(scale, scale_ref))
        self.assertTrue(torch.equal(zero_point, zp_ref))

    def test_choose_qparams_tensor_sym(self):
        input = torch.randn(10, 10)
        mapping_type = MappingType.SYMMETRIC
        dtype = torch.int8
        block_size = (10, 10)
        eps = torch.finfo(torch.float32).eps
        scale, zero_point = choose_qparams_affine(input, mapping_type, block_size, dtype, eps=eps)

        quant_min = -128
        quant_max = 127
        scale_ref, zp_ref = torch.ops.quantized_decomposed.choose_qparams_symmetric(input, quant_min, quant_max, eps, dtype)
        scale_ref = scale_ref.squeeze()
        zp_ref = zp_ref.squeeze()

        self.assertTrue(torch.equal(scale, scale_ref))
        self.assertTrue(torch.equal(zero_point, zp_ref))


    @unittest.skipIf(not TORCH_VERSION_AFTER_2_3, "skipping when torch verion is 2.3 or lower")
    def test_quantize_dequantize_group_sym(self):
        input = torch.randn(10, 10)
        mapping_type = MappingType.SYMMETRIC
        dtype = torch.int8
        block_size = (1, 2)
        scale, zero_point = choose_qparams_affine(input, mapping_type, block_size, dtype, eps=torch.finfo(torch.float32).eps)

        quantized = quantize_affine(input, block_size, scale, zero_point, dtype)
        dequantized = dequantize_affine(quantized, block_size, scale, zero_point, dtype, output_dtype=torch.float32)

        group_size = 2
        quant_min = -128
        quant_max = 127
        quantized_ref = torch.ops.quantized_decomposed.quantize_per_channel_group(
            input, scale, zero_point, quant_min, quant_max, torch.int8, group_size
        )
        dequantized_ref = torch.ops.quantized_decomposed.dequantize_per_channel_group(
            quantized_ref, scale, zero_point, quant_min, quant_max, torch.int8, group_size, output_dtype=torch.float32
        )

        self.assertTrue(torch.equal(quantized, quantized_ref))
        self.assertTrue(torch.equal(dequantized, dequantized_ref))

    @unittest.skipIf(not TORCH_VERSION_AFTER_2_4, "skipping when torch verion is 2.4 or lower")
    def test_quantize_dequantize_channel_asym(self):
        input = torch.randn(10, 10)
        mapping_type = MappingType.ASYMMETRIC
        dtype = torch.int8
        block_size = (10, 1)
        scale, zero_point = choose_qparams_affine(input, mapping_type, block_size, dtype, eps=torch.finfo(torch.float32).eps)
        output_dtype = torch.float32
        quantized = quantize_affine(input, block_size, scale, zero_point, dtype)
        dequantized = dequantize_affine(quantized, block_size, scale, zero_point, dtype, output_dtype=output_dtype)

        axis = 1
        quant_min = -128
        quant_max = 127
        quantized_ref = torch.ops.quantized_decomposed.quantize_per_channel(
            input, scale, zero_point, axis, quant_min, quant_max, torch.int8
        )
        dequantized_ref = torch.ops.quantized_decomposed.dequantize_per_channel(
            quantized_ref, scale, zero_point, axis, quant_min, quant_max, torch.int8, out_dtype=output_dtype
        )
        self.assertTrue(torch.equal(quantized, quantized_ref))
        self.assertTrue(torch.equal(dequantized, dequantized_ref))

    @unittest.skipIf(not TORCH_VERSION_AFTER_2_4, "skipping when torch verion is 2.4 or lower")
    def test_quantize_dequantize_tensor_asym(self):
        input = torch.randn(10, 10)
        mapping_type = MappingType.ASYMMETRIC
        dtype = torch.int8
        block_size = (10, 10)
        output_dtype = torch.float32
        scale, zero_point = choose_qparams_affine(input, mapping_type, block_size, dtype, eps=torch.finfo(torch.float32).eps)
        quantized = quantize_affine(input, block_size, scale, zero_point, dtype)
        dequantized = dequantize_affine(quantized, block_size, scale, zero_point, dtype, output_dtype=output_dtype)

        axis = 1
        quant_min = -128
        quant_max = 127
        quantized_ref = torch.ops.quantized_decomposed.quantize_per_tensor(
            input, scale, zero_point, quant_min, quant_max, torch.int8
        )
        dequantized_ref = torch.ops.quantized_decomposed.dequantize_per_tensor(
            quantized_ref, scale, zero_point, quant_min, quant_max, torch.int8, out_dtype=output_dtype
        )
        self.assertTrue(torch.equal(quantized, quantized_ref))
        self.assertTrue(torch.equal(dequantized, dequantized_ref))

    @unittest.skipIf(not TORCH_VERSION_AFTER_2_4, "skipping when torch verion is 2.4 or lower")
    def test_quantize_dequantize_channel_asym_4d(self):
        input = torch.randn(3, 3, 10, 10)
        mapping_type = MappingType.ASYMMETRIC
        dtype = torch.int8
        block_size = (3, 3, 1, 10)
        scale, zero_point = choose_qparams_affine(input, mapping_type, block_size, dtype, eps=torch.finfo(torch.float32).eps)
        quantized = quantize_affine(input, block_size, scale, zero_point, dtype)
        dequantized = dequantize_affine(quantized, block_size, scale, zero_point, dtype, output_dtype=torch.float32)

        axis = 2
        quant_min = -128
        quant_max = 127
        quantized_ref = torch.ops.quantized_decomposed.quantize_per_channel(
            input, scale, zero_point, axis, quant_min, quant_max, torch.int8
        )
        dequantized_ref = torch.ops.quantized_decomposed.dequantize_per_channel(
            quantized_ref, scale, zero_point, axis, quant_min, quant_max, torch.int8, out_dtype=torch.float32
        )
        self.assertTrue(torch.equal(quantized, quantized_ref))
        self.assertTrue(torch.equal(dequantized, dequantized_ref))

    @unittest.skipIf(not TORCH_VERSION_AFTER_2_3, "skipping when torch verion is 2.3 or lower")
    def test_quantize_dequantize_channel_asym_4d_multi_dim_reduction(self):
        input = torch.randn(3, 3, 10, 10)
        mapping_type = MappingType.ASYMMETRIC
        dtype = torch.int8
        block_size = (3, 3, 2, 2)
        scale, zero_point = choose_qparams_affine(input, mapping_type, block_size, dtype, eps=torch.finfo(torch.float32).eps)
        quantized = quantize_affine(input, block_size, scale, zero_point, dtype)
        dequantized = dequantize_affine(quantized, block_size, scale, zero_point, dtype, output_dtype=torch.float32)
        # we don't have corresponding ops in existing primitives, so just make sure it runs and it's close to float
        torch.testing.assert_allclose(dequantized, input, rtol=2, atol=0.02)


if __name__ == "__main__":
    unittest.main()
