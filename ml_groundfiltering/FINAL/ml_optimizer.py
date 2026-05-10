import os
import pickle
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score
from sklearn.preprocessing import LabelEncoder

from feature_extraction import FEATURE_NAMES, extract_training_samples


@dataclass
class FilterPrediction:
    pipeline: str
    title: str
    confidence: float


class MLFilterOptimizer:
    def __init__(self, model_path: str = "optimizer_model.pkl"):
        self.model_path = model_path
        self.model = RandomForestClassifier(
            n_estimators=300,
            random_state=42,
            class_weight="balanced",
            min_samples_leaf=1,
        )
        self.label_encoder = LabelEncoder()
        self.pipeline_titles: Dict[str, str] = {}
        self.feature_names: List[str] = list(FEATURE_NAMES)
        self.is_trained = False

    def train(
        self,
        X_train: Iterable[Iterable[float]],
        y_train: Iterable[str],
        pipeline_titles: Optional[Dict[str, str]] = None,
    ) -> float:
        """
        Train the model on geometric features and AFwizard pipeline labels.

        The target label is the AFwizard `properties.pipeline` hash, not a file
        path. This matches the way AFwizard resolves filters from libraries.
        """
        X_array = np.asarray(list(X_train), dtype=float)
        y_values = [str(value) for value in y_train]

        if X_array.ndim != 2 or X_array.shape[0] == 0:
            raise ValueError("No training feature vectors were provided.")
        if len(y_values) != X_array.shape[0]:
            raise ValueError("Feature and label counts do not match.")

        encoded_y = self.label_encoder.fit_transform(y_values)
        self.model.fit(X_array, encoded_y)
        self.pipeline_titles = dict(pipeline_titles or {})
        self.is_trained = True
        self._save_model()

        train_predictions = self.model.predict(X_array)
        return float(accuracy_score(encoded_y, train_predictions))

    def train_from_assigned_geojson(
        self,
        laz_path: str,
        assigned_geojson_path: str,
        cell_size: float = 40.0,
        min_points: int = 30,
    ) -> dict:
        """
        Train from a manually assigned AFwizard segmentation.

        The segmentation must contain `properties.pipeline` values produced by
        AFwizard's assign_pipeline workflow or by an equivalent scoring script.
        """
        X_train, y_train, titles, samples = extract_training_samples(
            laz_path,
            assigned_geojson_path,
            cell_size=cell_size,
            min_points=min_points,
        )
        training_accuracy = self.train(X_train, y_train, pipeline_titles=titles)

        return {
            "samples": len(samples),
            "classes": len(set(y_train)),
            "training_accuracy": training_accuracy,
            "class_counts": {
                label: int(y_train.count(label)) for label in sorted(set(y_train))
            },
        }

    def load(self) -> None:
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(self.model_path)

        with open(self.model_path, "rb") as file:
            payload = pickle.load(file)

        if not isinstance(payload, dict) or "model" not in payload:
            raise ValueError(
                "The model file uses an old demo format. Delete it or retrain with --retrain."
            )

        self.model = payload["model"]
        self.label_encoder = payload["label_encoder"]
        self.pipeline_titles = payload.get("pipeline_titles", {})
        self.feature_names = payload.get("feature_names", list(FEATURE_NAMES))
        self.is_trained = True

    def load_or_train(
        self,
        train_las: Optional[str],
        train_geojson: Optional[str],
        retrain: bool = False,
        cell_size: float = 40.0,
        min_points: int = 30,
    ) -> Optional[dict]:
        if os.path.exists(self.model_path) and not retrain:
            self.load()
            return None

        if not train_las or not train_geojson:
            raise ValueError(
                "A trained model was not found. Provide --train-las and --train-geojson."
            )

        return self.train_from_assigned_geojson(
            train_las,
            train_geojson,
            cell_size=cell_size,
            min_points=min_points,
        )

    def predict_from_samples(self, feature_vectors: Iterable[Iterable[float]]) -> FilterPrediction:
        if not self.is_trained:
            self.load()

        features_array = np.asarray(list(feature_vectors), dtype=float)
        if features_array.ndim == 1:
            features_array = features_array.reshape(1, -1)
        if features_array.ndim != 2 or features_array.shape[0] == 0:
            raise ValueError("No feature vectors were provided for prediction.")

        confidence = 1.0
        if hasattr(self.model, "predict_proba"):
            probabilities = self.model.predict_proba(features_array)
            mean_probabilities = np.mean(probabilities, axis=0)
            class_index = int(np.argmax(mean_probabilities))
            encoded_prediction = int(self.model.classes_[class_index])
            confidence = float(mean_probabilities[class_index])
        else:
            predictions = self.model.predict(features_array)
            labels, counts = np.unique(predictions, return_counts=True)
            class_index = int(np.argmax(counts))
            encoded_prediction = int(labels[class_index])
            confidence = float(counts[class_index] / np.sum(counts))

        pipeline = str(self.label_encoder.inverse_transform([encoded_prediction])[0])

        return FilterPrediction(
            pipeline=pipeline,
            title=self.pipeline_titles.get(pipeline, pipeline),
            confidence=confidence,
        )

    def predict(self, features: Iterable[float]) -> FilterPrediction:
        return self.predict_from_samples([features])

    def predict_best_filter(self, features: Iterable[float]) -> str:
        """Compatibility wrapper for older code."""
        return self.predict(features).pipeline

    def _save_model(self) -> None:
        payload = {
            "model": self.model,
            "label_encoder": self.label_encoder,
            "pipeline_titles": self.pipeline_titles,
            "feature_names": self.feature_names,
        }
        with open(self.model_path, "wb") as file:
            pickle.dump(payload, file)
