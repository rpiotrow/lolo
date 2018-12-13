from abc import abstractmethod, ABCMeta

import sys
import numpy as np
from lolopy.loloserver import get_java_gateway
from sklearn.base import BaseEstimator, RegressorMixin, ClassifierMixin, is_regressor


class BaseLoloLearner(BaseEstimator, metaclass=ABCMeta):
    """Base object for all leaners that use Lolo.

    Contains logic for starting the JVM gateway, and the fit operations.
    It is only necessary to implement the `_make_learner` object for """

    def __init__(self):
        self.gateway = get_java_gateway()

        # Create a placeholder for the model
        self.model_ = None

    def fit(self, X, y, weights=None):
        # Instantiate the JVM object
        learner = self._make_learner()

        # Convert all of the training data to Java arrays
        train_data, weights_java = self._convert_train_data(X, y, weights)
        assert train_data.length() == len(X), "Array copy failed"
        assert train_data.head()._1().length() == len(X[0]), "Wrong number of features"
        assert weights_java.length() == len(X), "Weights copy failed"

        # Train the model
        result = learner.train(train_data, self.gateway.jvm.scala.Some(weights_java))

        # Get the model out
        self.model_ = result.getModel()

        return self

    @abstractmethod
    def _make_learner(self):
        """Instantiate the learner used by Lolo to train a model

        Returns:
            (JavaObject) A lolo "Learner" object, which can be used to train a model"""
        pass

    def _convert_train_data(self, X, y, weights=None):
        """Convert the training data to a form accepted by Lolo

        Args:
            X (ndarray): Input variables
            y (ndarray): Output variables
            weights (ndarray): Wegihts for each sample
        Returns
            train_data (JavaObject): Pointer to the training data in Java
        """

        # Make some default weights
        if weights is None:
            weights = np.ones(len(y))

        # Convert x, y, and w to float64 and int8 with native ordering
        X = np.array(X, dtype=np.float64)
        y = np.array(y, dtype=np.float64 if is_regressor(self) else np.int32)
        weights = np.array(weights, dtype=np.float64)
        big_end = sys.byteorder == "big"

        # Convert X and y to Java Objects
        X_java = self.gateway.jvm.io.citrine.lolo.util.LoloPyDataLoader.getFeatureArray(X.tobytes(), X.shape[1], big_end)
        y_java = self.gateway.jvm.io.citrine.lolo.util.LoloPyDataLoader.get1DArray(y.tobytes(), is_regressor(self), big_end)
        assert y_java.length() == len(y) == len(X)
        w_java = self.gateway.jvm.io.citrine.lolo.util.LoloPyDataLoader.get1DArray(np.array(weights).tobytes(), True, big_end)
        assert w_java.length() == len(weights)

        return self.gateway.jvm.io.citrine.lolo.util.LoloPyDataLoader.zipTrainingData(X_java, y_java), w_java

    def _convert_run_data(self, X):
        """Convert the data to be run by the model

        Args:
            X (ndarray): Input data
        Returns:
            (JavaObject): Pointer to run data in Java
        """

        return self.gateway.jvm.io.citrine.lolo.util.LoloPyDataLoader.getFeatureArray(X.tobytes(), X.shape[1], False)


class BaseRandomForest(BaseLoloLearner):
    """Random Forest """

    def __init__(self, num_trees=-1, useJackknife=True, subsetStrategy="auto"):
        """Initialize the RandomForest

        Args:
            num_trees (int): Number of trees to use in the forest
        """
        super(BaseRandomForest, self).__init__()

        # Get JVM for this object

        # Store the variables
        self.num_trees = num_trees
        self.useJackknife = useJackknife
        self.subsetStrategy = subsetStrategy

    def _make_learner(self):
        #  TODO: Figure our a more succinct way of dealing with optional arguments/Option values
        #  TODO: Do not hard-code use of RandomForest
        learner = self.gateway.jvm.io.citrine.lolo.learners.RandomForest(
            self.num_trees, self.useJackknife,
            getattr(self.gateway.jvm.io.citrine.lolo.learners.RandomForest,
                    "$lessinit$greater$default$3")(),
            getattr(self.gateway.jvm.io.citrine.lolo.learners.RandomForest,
                    "$lessinit$greater$default$4")(),
            self.subsetStrategy
        )
        return learner

    def predict(self, X, return_std=False):
        # Convert the data to Java
        X_java = self._convert_run_data(X)

        # Get the PredictionResult
        pred_result = self.model_.transform(X_java)

        # Pull out the expected values
        y_pred = self.gateway.jvm.io.citrine.lolo.util.LoloPyDataLoader.getRegressionExpected(pred_result)
        y_pred = np.frombuffer(y_pred, dtype='float')  # Lolo gives a byte array back

        # If desired, return the uncertainty too
        if return_std:
            # TODO: This part fails on Windows because the NativeSystemBLAS is not found. Fix that
            # TODO: This is only valid for regression models. Perhaps make a "LoloRegressor" class
            y_std = self.gateway.jvm.io.citrine.lolo.util.LoloPyDataLoader.getRegressionUncertainty(pred_result)
            y_std = np.frombuffer(y_std, 'float')
            return y_pred, y_std

        # Get the expected values
        return y_pred


class RandomForestRegressor(BaseRandomForest, RegressorMixin):
    """Random Forest for regression"""
    pass


class RandomForestClassifier(BaseRandomForest, ClassifierMixin):

    def fit(self, X, y, weights=None):
        # Get the number of classes
        self.n_classes_ = len(set(y))

        return super(RandomForestClassifier, self).fit(X, y, weights)

    def predict(self, X):
        # Convert the data to Java
        X_java = self._convert_run_data(X)

        # Get the PredictionResult
        pred_result = self.model_.transform(X_java)

        # Pull out the expected values
        y_pred = self.gateway.jvm.io.citrine.lolo.util.LoloPyDataLoader.getClassifierExpected(pred_result)
        y_pred = np.frombuffer(y_pred, dtype=np.int32)  # Lolo gives a byte array back

        return y_pred

    def predict_proba(self, X):
        # Convert the data to Java
        X_java = self._convert_run_data(X)

        # Get the PredictionResult
        pred_result = self.model_.transform(X_java)

        # Copy over the class probabilities
        output = self.gateway.jvm.io.citrine.lolo.util.LoloPyDataLoader.getClassifierProbabilities(pred_result,
                                                                                                   self.n_classes_)
        output = np.frombuffer(output, dtype='float').reshape(-1, self.n_classes_)
        return output
