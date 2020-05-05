package io.citrine.lolo.trees

import scala.collection.mutable

/**
  * Description of a feature's effect on the weight ascribed to the node
  *
  * Decision trees can be thought of as weighted sums over their leaves.  When there is knowledge of every feature,
  * all of the weight goes into a single leaf.  However, when feature are excluded from the prediction, then both
  * paths of decisions that depend on those excluded features are assigned non-zero weights that are proportional to
  * the share of the training data that followed that path.
  *
  * This class captures those weights for a single feature and a single node.  The `featureIndex` identifies
  * which feature is having its effect described.  The `weightWhenIncluded` gives the factor of the weight of the node
  * due to this feature when the feature is included (i.e. known).  It is always 0 or 1.  The `weightWhenExcluded` gives
  * the factor of the weight of the node due to this feature when the feature is excluded (i.e. unknown).  It is always
  * strictly greater than 0 and strictly less than 1.
  *
  * @param featureIndex index of the feature this node describes.
  * @param weightWhenExcluded fraction of paths flowing through this node with this feature excluded.
  * @param weightWhenIncluded fraction of one paths flowing through this node with this feature included.
  */
case class FeatureWeightFactor(
                          featureIndex: Int,
                          weightWhenExcluded: Double,
                          weightWhenIncluded: Double
                 ) {
  require(weightWhenIncluded == 0.0 || weightWhenIncluded == 1.0,
    s"Got weightWhenIncluded=$weightWhenIncluded, but should only ever be 0.0 or 1.0")
  require(weightWhenExcluded > 0 && weightWhenExcluded < 1,
    s"Got weightWhenExcluded=$weightWhenExcluded, but should be > 0 and < 1")
}

/**
  * Path of unique features used in splitting to arrive at a node in a decision tree
  *
  * Note: DecisionPath.size is the number of splitting features. This does NOT include the first
  * node, which accounts for the "empty path" in computing TreeSHAP.
  *
  * The path is extended as new features are encountered, but it actually isn't supposed to represent the sequence
  * of features that are added.  Rather, each element in `weightBySubsetSize` corresponds to all of the subsets of the
  * features that are included vs excluded of a given size:
  *  - the 0th element corresponds to the path where all of the encountered features are excluded,
  *  - the 1st element sums the paths that have exactly one of the encountered feature included,
  *  - the 2nd element sums the paths that have exactly two of the encountered features included,
  * and so on and so forth.  The final element represents the single case where all of the features are "turned on".
  * This arrangement is convenient for computing combinatorial factors that depend on the feature subset size.
  *
  * @param numFeatures number of features in the input space (used for pre-allocation)
  */
class DecisionPath(numFeatures: Int) {
  // pre-allocation of this whole array is an attempted performance optimization.
  var features: mutable.Set[FeatureWeightFactor] = mutable.Set.empty
  val weightBySubsetSize: Array[Double] = Array(1.0) ++ Array.fill[Double](numFeatures + 1)(0.0)
  var size: Int = -1  // Start at -1 since first path extension accounts for 0 active features.

  /**
    * Extend the path by adding a new feature (in-place)
    *
    * @param weightWhenExcluded fraction of paths flowing through this node with this feature excluded
    * @param weightWhenIncluded fraction of one paths flowing through this node with this feature included
    * @param featureIndex index of feature, within the vector of inputs, used in this split with which to extend the path.
    * @return this (in-place)
    */
  def extend(
              weightWhenExcluded: Double,
              weightWhenIncluded: Double,
              featureIndex: Int
            ): DecisionPath = {
    size += 1
    // This handles the base case when shapely is first called in the trunk of the tree
    if (featureIndex >= 0) {
      features.add(FeatureWeightFactor(featureIndex, weightWhenExcluded, weightWhenIncluded))
    }

    (size-1 to 0 by -1).foreach{ i =>
      weightBySubsetSize(i+1) += weightWhenIncluded * weightBySubsetSize(i) * ((i + 1).toDouble/(size + 1))
      weightBySubsetSize(i) = weightWhenExcluded * weightBySubsetSize(i) * ((size - i).toDouble/(size + 1))
    }

    this
  }

  /**
    * Undo a previous extension of the feature path by removing a feature by its index (out-of-place)
    *
    * This method is probably better called "remove", but it is called unwind in the paper
    *
    * @param featureIndex index of the feature to remove (same as when extending)
    * @return unwound copy of this path.
    */
  def unwind(featureIndex: Int): DecisionPath = {
    // make a copy so this is out of place
    val out = this.copy()

    // find the FeatureWeightFactor to remove, and remove it
    val toRemove = features.find(_.featureIndex == featureIndex) match {
      case Some(x) =>
        out.features.remove(x)
        x
      case None =>
        throw new IllegalArgumentException(s"Cannot remove featureIndex=$featureIndex; it doesn't exist in the FeaturePath.")
    }

    // reverse the procedure in extend
    var n = out.weightBySubsetSize(size)
    (size-1 to 0 by -1).foreach{ j=>
      if (toRemove.weightWhenIncluded != 0.0) {
        val t = out.weightBySubsetSize(j)
        out.weightBySubsetSize(j) = n*(size + 1)/((j + 1)*toRemove.weightWhenIncluded)
        n = t - out.weightBySubsetSize(j) * toRemove.weightWhenExcluded * ((size - j).toDouble/(size + 1))
      } else {
        out.weightBySubsetSize(j) = out.weightBySubsetSize(j)*(size + 1).toDouble/(toRemove.weightWhenExcluded*(size - j))
      }
    }

    // bookkeeping
    out.size -= 1
    out
  }

  /**
    * Get the total weight in this decision path, as a sum over contributions from each size of the feature subsets
    */
  def totalWeight: Double = weightBySubsetSize.take(size + 1).sum

  def copy(): DecisionPath = {
    val newPath = new DecisionPath(this.numFeatures)
    newPath.size = this.size
    this.features.foreach(x => newPath.features.add(x.copy()))
    this.weightBySubsetSize.zipWithIndex.foreach{case (x, i) => newPath.weightBySubsetSize(i) = x}
    newPath
  }


}