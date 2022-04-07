# Copyright 2021 The TensorFlow Probability Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ============================================================================
"""Tests for MultiTaskGaussianProcessRegressionModel."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

# Dependency imports

from absl.testing import parameterized
import numpy as np

import tensorflow.compat.v2 as tf

import tensorflow_probability as tfp
from tensorflow_probability.python import experimental as tfe
from tensorflow_probability.python.internal import test_util

tfd = tfp.distributions
tfk = tfp.math.psd_kernels


@test_util.test_all_tf_execution_regimes
class MultiTaskGaussianProcessRegressionModelTest(
    test_util.TestCase):
  # TODO(b/202181168): Add shape inference tests with None shapes.

  def testMeanShapeBroadcasts(self):
    observation_index_points = tf.Variable(
        np.random.random((10, 5)), dtype=np.float32)
    observations = tf.Variable(np.random.random((10, 3)), dtype=np.float32)
    index_points = tf.Variable(np.random.random((4, 5)), dtype=np.float32)
    kernel = tfk.ExponentiatedQuadratic()
    multi_task_kernel = tfe.psd_kernels.Independent(
        num_tasks=3, base_kernel=kernel)
    mean = tf.Variable(np.random.random((3,)), dtype=np.float32)
    gp = tfe.distributions.MultiTaskGaussianProcessRegressionModel(
        multi_task_kernel,
        observation_index_points=observation_index_points,
        observations=observations,
        index_points=index_points,
        mean_fn=lambda _: mean,
        observation_noise_variance=np.float32(1e-2))
    self.assertAllEqual(self.evaluate(gp.event_shape_tensor()), [4, 3])

  @parameterized.parameters(1, 3, 5)
  def testShapes(self, num_tasks):
    # 3x3 grid of index points in R^2 and flatten to 9x2
    index_points = np.linspace(-4., 4., 3, dtype=np.float64)
    index_points = np.stack(np.meshgrid(index_points, index_points), axis=-1)
    index_points = np.reshape(index_points, [-1, 2])

    batched_index_points = np.stack([index_points]*6)
    # ==> shape = [6, 9, 2]

    # ==> shape = [9, 2]
    observations = np.linspace(-20., 20., num_tasks * 9).reshape(9, num_tasks)

    test_index_points = np.random.uniform(-6., 6., [5, 2])
    # ==> shape = [3, 1, 5, 2]

    # Kernel with batch_shape [2, 4, 3, 1, 1]
    amplitude = np.array([1., 2.], np.float64).reshape([2, 1, 1, 1])
    length_scale = np.array([1., 2., 3., 4.], np.float64).reshape([1, 4, 1, 1])
    observation_noise_variance = np.array(
        [1e-5, 1e-6, 1e-5], np.float64).reshape([1, 1, 3, 1])
    kernel = tfk.ExponentiatedQuadratic(amplitude, length_scale)
    multi_task_kernel = tfe.psd_kernels.Independent(
        num_tasks=num_tasks, base_kernel=kernel)
    gp = tfe.distributions.MultiTaskGaussianProcessRegressionModel(
        multi_task_kernel,
        observation_index_points=batched_index_points,
        observations=observations,
        index_points=test_index_points,
        observation_noise_variance=observation_noise_variance,
        predictive_noise_variance=0.,
        validate_args=True)

    batch_shape = [2, 4, 3, 6]
    event_shape = [5, num_tasks]
    sample_shape = [5, 3]

    samples = gp.sample(sample_shape, seed=test_util.test_seed())

    self.assertAllEqual(gp.batch_shape, batch_shape)
    self.assertAllEqual(gp.event_shape, event_shape)
    self.assertAllEqual(self.evaluate(gp.batch_shape_tensor()), batch_shape)
    self.assertAllEqual(self.evaluate(gp.event_shape_tensor()), event_shape)
    self.assertAllEqual(
        self.evaluate(samples).shape,
        sample_shape + batch_shape + event_shape)
    self.assertAllEqual(
        self.evaluate(gp.log_prob(samples)).shape,
        sample_shape + batch_shape)
    self.assertAllEqual(
        self.evaluate(tf.shape(gp.mean())), batch_shape + event_shape)

  @parameterized.parameters(1, 3, 5)
  def testBindingIndexPoints(self, num_tasks):
    amplitude = np.float64(0.5)
    length_scale = np.float64(2.)
    kernel = tfk.ExponentiatedQuadratic(amplitude, length_scale)

    # 5x5 grid of index points in R^2 and flatten to 9x2
    index_points = np.linspace(-4., 4., 3, dtype=np.float64)
    index_points = np.stack(np.meshgrid(index_points, index_points), axis=-1)
    observation_index_points = np.reshape(index_points, [-1, 2])
    # ==> shape = [9, 2]

    observations = np.linspace(-20., 20., 9 * num_tasks).reshape(9, num_tasks)

    multi_task_kernel = tfe.psd_kernels.Independent(
        num_tasks=num_tasks, base_kernel=kernel)
    observation_noise_variance = np.float64(1e-2)
    mtgp = tfe.distributions.MultiTaskGaussianProcessRegressionModel(
        kernel=multi_task_kernel,
        observation_index_points=observation_index_points,
        observations=observations,
        observation_noise_variance=observation_noise_variance,
        validate_args=True)
    gp = tfd.GaussianProcessRegressionModel(
        kernel=kernel,
        observation_index_points=observation_index_points,
        # Batch of num_task observations.
        observations=tf.linalg.matrix_transpose(observations),
        observation_noise_variance=observation_noise_variance,
        validate_args=True)

    test_points = np.random.uniform(-1., 1., [10, 2])
    test_observations = np.random.uniform(-1., 1., [10, num_tasks])

    multi_task_log_prob = mtgp.log_prob(
        test_observations, index_points=test_points)
    # Reduce over the first dimension which is tasks.
    single_task_log_prob = tf.reduce_sum(
        gp.log_prob(
            tf.linalg.matrix_transpose(test_observations),
            index_points=test_points), axis=0)
    self.assertAllClose(
        self.evaluate(single_task_log_prob),
        self.evaluate(multi_task_log_prob), rtol=1e-5)

    multi_task_mean_ = self.evaluate(mtgp.mean(index_points=test_points))
    # Reshape so that task dimension is last.
    single_task_mean_ = np.swapaxes(
        self.evaluate(gp.mean(index_points=test_points)),
        -1, -2)
    self.assertAllClose(
        single_task_mean_, multi_task_mean_, rtol=1e-5)

  @parameterized.parameters(1, 3, 5)
  def testLogProbMatchesGPNoiseless(self, num_tasks):
    # Check that the independent kernel parameterization matches using a
    # single-task GP.

    # 5x5 grid of index points in R^2 and flatten to 9x2
    index_points = np.linspace(-4., 4., 3, dtype=np.float32)
    index_points = np.stack(np.meshgrid(index_points, index_points), axis=-1)
    index_points = np.reshape(index_points, [-1, 2])
    # ==> shape = [9, 2]

    amplitude = np.float32(0.5)
    length_scale = np.float32(2.)
    kernel = tfk.ExponentiatedQuadratic(amplitude, length_scale)
    observation_noise_variance = None
    multi_task_kernel = tfe.psd_kernels.Independent(
        num_tasks=num_tasks, base_kernel=kernel)

    observations = np.linspace(
        -20., 20., 9 * num_tasks).reshape(9, num_tasks).astype(np.float32)

    test_points = np.random.uniform(-1., 1., [10, 2]).astype(np.float32)
    test_observations = np.random.uniform(
        -20., 20., [10, num_tasks]).astype(np.float32)

    mtgp = tfe.distributions.MultiTaskGaussianProcessRegressionModel(
        multi_task_kernel,
        observation_index_points=index_points,
        index_points=test_points,
        observations=observations,
        observation_noise_variance=observation_noise_variance,
        validate_args=True)

    # For the single task GP, we move the task dimension to the front of the
    # batch shape.
    gp = tfd.GaussianProcessRegressionModel(
        kernel,
        observation_index_points=index_points,
        index_points=test_points,
        observations=tf.linalg.matrix_transpose(observations),
        observation_noise_variance=0.,
        validate_args=True)
    multitask_log_prob = mtgp.log_prob(test_observations)
    single_task_log_prob = tf.reduce_sum(
        gp.log_prob(
            tf.linalg.matrix_transpose(test_observations)), axis=0)
    self.assertAllClose(
        self.evaluate(single_task_log_prob),
        self.evaluate(multitask_log_prob), rtol=4e-3)

    multi_task_mean_ = self.evaluate(mtgp.mean())
    # Reshape so that task dimension is last.
    single_task_mean_ = np.swapaxes(
        self.evaluate(gp.mean()), -1, -2)
    self.assertAllClose(
        single_task_mean_, multi_task_mean_, rtol=1e-5)

  @parameterized.parameters(1, 3, 5)
  def testLogProbMatchesGP(self, num_tasks):
    # Check that the independent kernel parameterization matches using a
    # single-task GP.

    # 5x5 grid of index points in R^2 and flatten to 9x2
    index_points = np.linspace(-4., 4., 3, dtype=np.float32)
    index_points = np.stack(np.meshgrid(index_points, index_points), axis=-1)
    index_points = np.reshape(index_points, [-1, 2])
    # ==> shape = [9, 2]

    amplitude = np.float32(0.5)
    length_scale = np.float32(2.)
    kernel = tfk.ExponentiatedQuadratic(amplitude, length_scale)
    observation_noise_variance = np.float32(1e-2)
    multi_task_kernel = tfe.psd_kernels.Independent(
        num_tasks=num_tasks, base_kernel=kernel)

    observations = np.linspace(
        -20., 20., 9 * num_tasks).reshape(9, num_tasks).astype(np.float32)

    test_points = np.random.uniform(-1., 1., [10, 2]).astype(np.float32)
    test_observations = np.random.uniform(
        -20., 20., [10, num_tasks]).astype(np.float32)

    mtgp = tfe.distributions.MultiTaskGaussianProcessRegressionModel(
        multi_task_kernel,
        observation_index_points=index_points,
        index_points=test_points,
        observations=observations,
        observation_noise_variance=observation_noise_variance,
        validate_args=True)

    # For the single task GP, we move the task dimension to the front of the
    # batch shape.
    gp = tfd.GaussianProcessRegressionModel(
        kernel,
        observation_index_points=index_points,
        index_points=test_points,
        observations=tf.linalg.matrix_transpose(observations),
        observation_noise_variance=observation_noise_variance,
        validate_args=True)
    # Print batch of covariance matrices.
    multitask_log_prob = mtgp.log_prob(test_observations)
    single_task_log_prob = tf.reduce_sum(
        gp.log_prob(
            tf.linalg.matrix_transpose(test_observations)), axis=0)
    self.assertAllClose(
        self.evaluate(single_task_log_prob),
        self.evaluate(multitask_log_prob), rtol=4e-3)

    multi_task_mean_ = self.evaluate(mtgp.mean())
    # Reshape so that task dimension is last.
    single_task_mean_ = np.swapaxes(
        self.evaluate(gp.mean()),
        -1, -2)
    self.assertAllClose(
        single_task_mean_, multi_task_mean_, rtol=1e-5)

  @parameterized.parameters(1, 3, 5)
  def testNonTrivialMeanMatchesGP(self, num_tasks):
    # Check that the independent kernel parameterization matches using a
    # single-task GP.

    # 5x5 grid of index points in R^2 and flatten to 9x2
    index_points = np.linspace(-4., 4., 3, dtype=np.float32)
    index_points = np.stack(np.meshgrid(index_points, index_points), axis=-1)
    index_points = np.reshape(index_points, [-1, 2])
    # ==> shape = [9, 2]

    amplitude = np.float32(0.5)
    length_scale = np.float32(2.)
    kernel = tfk.ExponentiatedQuadratic(amplitude, length_scale)
    observation_noise_variance = np.float32(1e-2)
    multi_task_kernel = tfe.psd_kernels.Independent(
        num_tasks=num_tasks, base_kernel=kernel)

    observations = np.linspace(
        -20., 20., 9 * num_tasks).reshape(9, num_tasks).astype(np.float32)

    test_points = np.random.uniform(-1., 1., [10, 2]).astype(np.float32)
    test_observations = np.random.uniform(
        -20., 20., [10, num_tasks]).astype(np.float32)

    # Constant mean per task.
    mean_fn = lambda x: tf.linspace(1., 3., num_tasks)

    mtgp = tfe.distributions.MultiTaskGaussianProcessRegressionModel(
        multi_task_kernel,
        observation_index_points=index_points,
        index_points=test_points,
        observations=observations,
        observation_noise_variance=observation_noise_variance,
        mean_fn=mean_fn,
        validate_args=True)

    # For the single task GP, we move the task dimension to the front of the
    # batch shape.
    gp = tfd.GaussianProcessRegressionModel(
        kernel,
        observation_index_points=index_points,
        index_points=test_points,
        observations=tf.linalg.matrix_transpose(observations),
        observation_noise_variance=observation_noise_variance,
        mean_fn=lambda x: tf.linspace(1., 3., num_tasks)[..., tf.newaxis],
        validate_args=True)
    # Print batch of covariance matrices.
    multitask_log_prob = mtgp.log_prob(test_observations)
    single_task_log_prob = tf.reduce_sum(
        gp.log_prob(
            tf.linalg.matrix_transpose(test_observations)), axis=0)
    self.assertAllClose(
        self.evaluate(single_task_log_prob),
        self.evaluate(multitask_log_prob), rtol=4e-3)

    multi_task_mean_ = self.evaluate(mtgp.mean())
    # Reshape so that task dimension is last.
    single_task_mean_ = np.swapaxes(
        self.evaluate(gp.mean()),
        -1, -2)
    self.assertAllClose(
        single_task_mean_, multi_task_mean_, rtol=1e-5)

  def testMasking(self):
    seed_idx, seed_obs, seed_test, seed_sample = (
        tfp.random.split_seed(test_util.test_seed(), 4))
    index_points = tfd.Uniform(-1., 1.).sample((4, 3, 2, 2), seed=seed_idx)
    observations = tfd.Uniform(-1., 1.).sample((4, 3, 2), seed=seed_obs)
    test_points = tfd.Uniform(-1., 1.).sample((4, 5, 2, 2), seed=seed_test)

    observations_is_missing = np.array([
        [[True, True], [False, True], [True, False]],
        [[False, True], [False, True], [False, True]],
        [[False, False], [True, True], [True, False]],
        [[True, False], [False, True], [False, False]]
    ])
    observations = tf.where(~observations_is_missing, observations, np.nan)

    amplitude = tf.convert_to_tensor([0.5, 1.0, 1.75, 3.5])
    length_scale = tf.convert_to_tensor([0.3, 0.6, 0.9, 1.2])
    kernel = tfe.psd_kernels.Independent(
        2,
        tfp.math.psd_kernels.ExponentiatedQuadratic(
            amplitude, length_scale, feature_ndims=2),
        validate_args=True)

    def mean_fn(x):
      return (tf.math.reduce_sum(x, axis=[-1, -2])[..., tf.newaxis]
              * tf.convert_to_tensor([-0.5, 2.0]))

    mtgp = tfe.distributions.MultiTaskGaussianProcessRegressionModel(
        kernel,
        observation_index_points=index_points,
        observations=observations,
        observations_is_missing=observations_is_missing,
        index_points=test_points,
        predictive_noise_variance=0.05,
        mean_fn=mean_fn,
        validate_args=True)

    # Compare to a GPRM where the task dimension has been moved to be the
    # rightmost batch dimension.
    gp = tfp.distributions.GaussianProcessRegressionModel.precompute_regression_model(
        kernel.base_kernel[..., tf.newaxis],
        observation_index_points=index_points[:, tf.newaxis],
        observations=tf.linalg.matrix_transpose(observations),
        observations_mask=~tf.linalg.matrix_transpose(observations_is_missing),
        index_points=test_points[:, tf.newaxis],
        predictive_noise_variance=0.05,
        mean_fn=lambda x: tf.linalg.matrix_transpose(mean_fn(x[:, 0])),
        validate_args=True)

    x = mtgp.sample(2, seed=seed_sample)
    self.assertAllNotNan(mtgp.log_prob(x))
    self.assertAllClose(
        tf.math.reduce_sum(gp.log_prob(tf.linalg.matrix_transpose(x)), axis=-1),
        mtgp.log_prob(x))

    self.assertAllNotNan(mtgp.mean())
    self.assertAllClose(tf.linalg.matrix_transpose(gp.mean()), mtgp.mean())

if __name__ == '__main__':
  test_util.main()
