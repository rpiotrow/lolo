from abc import abstractmethod, ABCMeta

import numpy as np
from lolopy.loloserver import get_java_gateway
from py4j.java_collections import ListConverter
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

        # Make the weights
        if weights is None:
            result = learner.train(train_data)
        else:
            # Call training with weights
            #  We encapsulate weights in "scale.Some" to make it an "Optional" class
            result = learner.train(train_data, self.gateway.jvm.scala.Some(weights_java))

        # Get the model out
        self.model_ = result.getModel()

        return self

    @abstractmethod
    def _make_learner(self):
        """Instantiate the learner used by Lolo to train a model

        Ret"""
        pass

    def _convert_train_data(self, X, y, weights=None):
        """Convert the training data to a form accepted by Lolo

        Args:
            X (ndarray): Input variables
            y (ndarray): Output variables
            weights (ndarray): Wegihts for each sample
        Returns
            train_data (JavaObject): Pointer to the training data in Java
            weights_java (JavaObject): POinter to the weights in Java, if provided
        """

        # Convert X and y to Java Objects
        train_data = self.gateway.jvm.java.util.ArrayList(len(y))
        for x_i, y_i in zip(X, y):
            # Copy the X into an array
            x_i_java = ListConverter().convert(x_i, self.gateway._gateway_client)
            x_i_java = self.gateway.jvm.scala.collection.JavaConverters.asScalaBuffer(
                x_i_java).toVector()

            # If a regression problem, make sure y_i is a float
            if is_regressor(self):
                y_i = float(y_i)
            else:
                y_i = int(y_i)

            # If weights are None, RF expects a 3ple
            if weights is None:
                pair = self.gateway.jvm.scala.Tuple3(x_i_java, y_i, 1.0)
            else:
                pair = self.gateway.jvm.scala.Tuple2(x_i_java, y_i)

            # Append to training data list
            train_data.append(pair)
        train_data = self.gateway.jvm.scala.collection.JavaConverters.asScalaBuffer(train_data)

        # Convert weights, if needed
        if weights is not None:
            # Convert weights to scala array
            weights_java = ListConverter().convert(weights, self.gateway._gateway_client)
            weights_java = self.gateway.jvm.scala.collection.JavaConverters.asScalaBuffer(weights_java)

            return train_data, weights_java

        return train_data, None

    def _convert_run_data(self, X):
        """Convert the data to be run by the model

        Args:
            X (ndarray): Input data
        Returns:
            (JavaObject): Pointer to run data in Java
        """

        # Convert X to an array
        X_java = self.gateway.jvm.java.util.ArrayList(len(X))
        for x_i in X:
            x_i_java = ListConverter().convert(x_i, self.gateway._gateway_client)
            x_i_java = self.gateway.jvm.scala.collection.JavaConverters.asScalaBuffer(
                x_i_java).toVector()
            X_java.append(x_i_java)
        X_java = self.gateway.jvm.scala.collection.JavaConverters.asScalaBuffer(X_java)
        return X_java


class BaseRandomForest(BaseLoloLearner):
    """Random Forest """

    def __init__(self, num_trees=-1, useJackknife=True, subsetStrategy=4):
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
        """Instantiate the learner used by Lolo to train a model

        Returns:
            (JavaObject) A lolo "Learner" object, which can be used to train a model
        """
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
        exp_values = pred_result.getExpected()
        y_pred = [exp_values.apply(i) for i in range(len(X))]

        # If desired, return the uncertainty too
        if return_std:
            # TODO: This part fails on Windows because the NativeSystemBLAS is not found. Fix that
            # TODO: This is only valid for regression models. Perhaps make a "LoloRegressor" class
            uncertain = pred_result.getUncertainty().get()
            y_std = np.zeros_like(y_pred)
            for i in range(len(X)):
                y_std[i] = uncertain.apply(i)
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
        return super(RandomForestClassifier, self).predict(X, False)

    def predict_proba(self, X):
        # Convert the data to Java
        X_java = self._convert_run_data(X)

        # Get the PredictionResult
        pred_result = self.model_.transform(X_java)

        # Copy over the class probabilities
        output = np.zeros((len(X), self.n_classes_))
        prob_array = pred_result.getUncertainty().get()
        for i, prob in enumerate(self.gateway.jvm.scala.collection.JavaConverters
                                         .asJavaCollection(prob_array).toArray()):
            prob = self.gateway.jvm.scala.collection.JavaConverters.mapAsJavaMap(prob)
            for j in range(self.n_classes_):
                output[i, j] = prob.getOrDefault(j, 0)
        return output
