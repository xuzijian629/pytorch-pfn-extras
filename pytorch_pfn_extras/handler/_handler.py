from collections import defaultdict
from typing import (
    Any, Callable, Dict, Generator, Iterable, List, Mapping, Optional,
    Tuple, Union, TYPE_CHECKING,
)

import torch
from typing_extensions import Protocol, runtime_checkable

import pytorch_pfn_extras as ppe
from pytorch_pfn_extras import reporting
from pytorch_pfn_extras.handler._logic import BaseLogic
from pytorch_pfn_extras.training import Evaluator, Trainer

if TYPE_CHECKING:
    from pytorch_pfn_extras.runtime import BaseRuntime


@runtime_checkable
class DeferredResult(Protocol):
    """
    Protocol that is used for models that work asynchronously
    """
    def done(self) -> bool:
        """Returns `True` when a deferred result is available."""
        raise NotImplementedError("done must be implemented")

    def wait(self) -> 'DeferredResult':
        """Does a blocking wait until the result is available.

        Returns self to allow chaining calls once the wait is over.
        """
        raise NotImplementedError("wait must be implemented")

    def get(self) -> Optional[Any]:
        """Returns the result when its available. ``None`` if its not ready"""
        raise NotImplementedError("get must be implemented")


class _DeferredIteration:

    def __init__(
            self,
            deferred: Union[DeferredResult, Dict[str, Union[Any, DeferredResult]]],
            idx: int,
            batch: Dict[str, Any],
            cback: Callable[..., None],
    ) -> None:
        self.deferred = deferred
        self.idx = idx
        self.batch = batch
        self.cback = cback


class BaseHandler:

    def __init__(
            self,
            logic: BaseLogic,
            options: Dict[str, Any],
            *args: Any,
            **kwargs: Any
    ) -> None:
        """Base class of Handler.

        .. seealso:
           :class:`pytorch_pfn_extras.handler.Handler`

        Args:
            logic (Logic): A logic.
        """
        super().__init__()
        options = options.copy() if options else {}
        self._logic = logic
        self.consume_options(options)

    def consume_options(self, options: Dict[str, Any]) -> None:
        """A method to update options of Handler.

        Note that the given dict will be modified.

        Args:
            options (dict): Option key-values to be set.

        .. seealso:
           :meth:`pytorch_pfn_extras.handler.Handler.consume_options`
        """
        pass

    def train_setup(self, trainer: Trainer, loader: Iterable[Any]) -> None:
        """A method called only once when starting a training run.

        .. seealso:
           :meth:`pytorch_pfn_extras.handler.Handler.train_step`
        """
        # Context: Trainer
        # Called only once when starting a training run.
        pass

    def train_epoch_begin(
            self,
            trainer: Trainer,
            loader: Iterable[Any]
    ) -> None:
        """A method called when starting a new epoch.

        .. seealso:
           :meth:`pytorch_pfn_extras.handler.Handler.train_epoch_begin`
        """
        # Context: Trainer
        # Called when starting a new epoch.
        pass

    def train_epoch_end(self, trainer: Trainer) -> None:
        """A method called when finishing an epoch.

        .. seealso:
           :meth:`pytorch_pfn_extras.handler.Handler.train_epoch_end`
        """
        # Context: Trainer
        # Called when finishing an epoch.
        pass

    def train_validation_begin(
            self,
            trainer: Trainer,
            evaluator: Evaluator,
    ) -> None:
        """A method called when starting a validation.

        .. seealso:
           :meth:`pytorch_pfn_extras.handler.Handler.train_validation_begin`
        """
        # Context: Trainer
        # Called just before starting a validation run, i.e. at the end of
        # every epoch in the training run.
        pass

    def train_validation_end(
            self,
            trainer: Trainer,
            evaluator: Evaluator,
    ) -> None:
        """A method called after validation.

        Args:
            trainer (Trainer): The trainer that calls this method.
            evaluator (Evaluator): The evaluator used for validation.
        """
        # Context: Trainer
        # Called after validation run, i.e. at the end of
        # every epoch in the training run.
        pass

    def train_step(
            self,
            trainer: Trainer,
            batch_idx: int,
            batch: Any,
            complete_fn: Callable[[int, Any], None],
    ) -> None:
        """A training step.

        .. seealso:
           :meth:`pytorch_pfn_extras.handler.Handler.train_step`
        """
        # Context: Trainer
        # Do a training iteration.
        pass

    def train_post_step(
            self,
            trainer: Trainer,
            batch_idx: int,
            batch: Any,
            outputs: Any,
    ) -> None:
        """A method called after each training step.

        .. seealso:
           :meth:`pytorch_pfn_extras.handler.Handler.train_post_step`
        """
        # Context: Trainer
        # Called after train_step.
        pass

    def eval_setup(
            self,
            evaluator: Evaluator,
            loader: Iterable[Any]
    ) -> None:
        """A method called only once when starting a training run.
        When evaluator is not given, this method is not called.

        .. seealso:
           :meth:`pytorch_pfn_extras.handler.Handler.eval_setup`
        """
        # Context: Evaluator
        # Called only once when starting a training run, when evaluator is
        # given.
        pass

    def eval_loop_begin(self, evaluator: Evaluator) -> None:
        """A method called before each evaluation step.

        Args:
            evaluator (Evaluator): The evaluator.
        """
        # Context: Evaluator
        # Called before running all the steps of the evaluation
        pass

    def eval_step(
            self,
            evaluator: Evaluator,
            batch_idx: int,
            batch: Any,
            complete_fn: Callable[[int, Any], None],
    ) -> None:
        """Evaluation iteration.

        .. seealso:
           :meth:`pytorch_pfn_extras.handler.Handler.eval_step`
        """
        # Context: Evaluator
        # Do an evaluation iteration.
        pass

    def eval_loop_end(self, evaluator: Evaluator) -> None:
        """A method called after running all steps of the evaluation.

        .. seealso:
           :meth:`pytorch_pfn_extras.handler.Handler.eval_loop_endp`
        """
        # Context: Evaluator
        # Called after running all the steps of the evaluation
        pass

    def eval_post_step(
            self,
            evaluator: Evaluator,
            batch_idx: int,
            batch: Any,
            outputs: Any,
    ) -> None:
        """A method called after each evaluation step.

        .. seealso:
           :meth:`pytorch_pfn_extras.handler.Handler.eval_post_step`
        """
        # Context: Evaluator
        # Called after eval_step.
        pass


ModulesTuple = Tuple[str, torch.nn.Module, 'BaseRuntime']
PendingIters = List[_DeferredIteration]


class Handler(BaseHandler):

    def __init__(
            self,
            logic: BaseLogic,
            entry_runtime: 'BaseRuntime',
            options: Dict[str, Any],
    ) -> None:
        """A set of callback functions to perform device-specific operations.

        Args:
            logic (Logic): A logic.
            entry_runtime (BaseRuntime): A runtime object.
            options (dict): The configuration options.

                * ``'eval_report_keys'`` (list of str):
                    A list of names of outputs that are given as inputs
                    of ``reporting.report`` after each evaluation step.
                    Default is an empty list.
                * ``'train_report_keys'`` (list of str):
                    A list of names of outputs that are given as inputs
                    of ``reporting.report`` after each training step.
                    Default is an empty list.
        """
        super().__init__(logic, options)
        self.pending_iters: Dict[str, PendingIters] = defaultdict(list)

        # This is used to send the batch to the appropiate device
        self._entry_runtime = entry_runtime
        self._ppe_modules: List[ModulesTuple] = []

    def consume_options(self, options: Dict[str, Any]) -> None:
        super().consume_options(options)
        self._eval_report_keys = options.pop('eval_report_keys', [])
        self._train_report_keys = options.pop('train_report_keys', [])
        # Consume this argument for backward compatibility
        options.pop('async', False)

    def _runtime_iterator(
            self,
            models: Mapping[str, torch.nn.Module],
    ) -> Generator[ModulesTuple, ModulesTuple, None]:
        if not self._ppe_modules:
            for n, m in models.items():
                for sn, sm in ppe.runtime._runtime.named_runtime_modules(m, n):
                    rt = ppe.runtime._runtime._module_runtime_tag(sm)
                    self._ppe_modules.append((sn, sm, rt))
                    yield sn, sm, rt
        else:
            for sn, sm, rt in self._ppe_modules:
                yield sn, sm, rt

    def _setup(
            self,
            models: Mapping[str, torch.nn.Module],
            loader: Union[Iterable[Any], Mapping[str, Iterable[Any]]],
            optimizers: Optional[Mapping[str, torch.optim.Optimizer]] = None,
    ) -> None:
        # This requires loader to be always a dict
        # should be avoided?
        if not isinstance(loader, dict):
            # The default model always has empty name when obtained from the
            # modules
            loaders = {sn: loader
                       for sn, _, _ in self._runtime_iterator(models)}
        else:
            loaders = loader
        if optimizers is None:
            optimizers = {}

        for sn, sm, rt in self._runtime_iterator(models):
            # users can give a tensor or loader in case
            # shape cannot be inferred for submodules
            # TODO the optimizers are also needed?
            optim = optimizers.get(sn, None)
            if optim is None and len(optimizers) == 1:
                optim = next(iter(optimizers.values()))
            load = loaders.get(sn, None)
            rt.initialize_module(sm, load, optim)

        if len(self._ppe_modules) == 0:
            raise RuntimeError(
                'call `ppe.to(module, device)` before starting the training')

    def train_setup(self, trainer: Trainer, loader: Iterable[Any]) -> None:
        """A method called only once when starting a training run.

        Args:
            trainer (Trainer): The trainer that calls this method.
            loader (torch.utils.data.DataLoader): The data loader.
        """
        for _, model in trainer.models.items():
            model.train()
        self._setup(trainer.models, loader, trainer.optimizers)

    def train_epoch_begin(
            self,
            trainer: Trainer,
            loader: Iterable[Any]
    ) -> None:
        """A method called when starting a new epoch.

        Args:
            trainer (Trainer): The trainer that calls this method.
            loader (torch.utils.data.DataLoader): The data loader.
        """
        for _, sm, rt in self._runtime_iterator(trainer.models):
            rt.train_epoch_begin(sm)

        self._logic.train_epoch_begin(trainer.models, trainer.epoch, loader)

    def train_epoch_end(self, trainer: Trainer) -> None:
        """A method called when finishing an epoch.

        Args:
            trainer (Trainer): The trainer that calls this method.
        """
        while self.pending_iters:
            for sn, sm, rt in self._runtime_iterator(trainer.models):
                t_outs = self._get_deferred_outputs(
                    self.pending_iters[sn][0], True)
                self._complete_train_step(
                    trainer, t_outs, True, sn, sm, rt)

        self._logic.train_epoch_end(trainer.models, trainer.epoch)

    def train_validation_begin(
            self,
            trainer: Trainer,
            evaluator: Evaluator,
    ) -> None:
        """A method called when starting a validation.

        Args:
            evaluator (Evaluator): An evaluator.
        """
        # We need to correlate the models in trainer and evaluator
        for _, sm, rt in self._runtime_iterator(evaluator.models):
            rt.train_validation_begin(sm)
        self._logic.train_validation_begin(evaluator.models)

    def train_validation_end(
            self,
            trainer: Trainer,
            evaluator: Evaluator,
    ) -> None:
        """A method called after validation.

        Args:
            trainer (Trainer): The trainer that calls this method.
            evaluator (Evaluator): The evaluator used for validation.
        """
        # Context: Trainer
        # Called after validation run, i.e. at the end of
        # every epoch in the training run.
        # We need to correlate the models in trainer and evaluator
        for _, sm, rt in self._runtime_iterator(evaluator.models):
            rt.train_validation_end(sm)

        self._logic.train_validation_end(evaluator.models)

    def _complete_train_step(
            self, trainer: Trainer, outs: Any, block: bool,
            sn: str, sm: torch.nn.Module, rt: 'BaseRuntime',
    ) -> None:
        p_iter = self.pending_iters[sn][0]
        self.pending_iters[sn] = self.pending_iters[sn][1:]
        # Since async mode is not supported with device splitting
        # we know that there is only ONE submodule, so we
        # can asure that now we can step the optimizers
        self._logic.train_step_optimizers(
            trainer.models, trainer.optimizers, p_iter.idx)
        if len(self.pending_iters[sn]) == 0:
            del self.pending_iters[sn]
        p_iter.cback(p_iter.idx, outs, is_deferred=block)

    def _are_outs_deferred(self, outs: Any) -> bool:
        if isinstance(outs, DeferredResult):
            return True
        if isinstance(outs, dict):
            for _, v in outs.items():
                if isinstance(v, DeferredResult):
                    return True
        return False

    def _get_deferred_outputs(
        self,
        p_iter: _DeferredIteration,
        wait: bool = False,
    ) -> Any:
        # async returns inmediately
        # Check if there is a completed iteration
        # If we enqueue everything first, we will blow up with
        # memory due to the dataloaders being in the background
        # We need to call the tagged runtimes since async mode
        # require different treatment depending on the device.
        t_outs: Optional[Dict[str, Any]] = None
        if isinstance(p_iter.deferred, dict):
            t_outs = {}
            for k, v in p_iter.deferred.items():
                if isinstance(v, DeferredResult):
                    is_done = v.done()
                    if not is_done and wait:
                        v.wait()
                    elif not is_done:
                        return None
                    t_outs[k] = v.get()
                else:
                    t_outs[k] = v
        else:
            is_done = p_iter.deferred.done()
            if not is_done and wait:
                p_iter.deferred.wait()
                t_outs = p_iter.deferred.get()
            elif is_done:
                t_outs = p_iter.deferred.get()
        return t_outs

    def train_step(
            self,
            trainer: Trainer,
            batch_idx: int,
            batch: Any,
            complete_fn: Callable[[int, Any], None],
    ) -> None:
        """A training step.

        Args:
            trainer (Trainer): A trainer.
            batch_idx (int): Number of iterations already finished.
            batch (dict of torch.Tensor): Input tensors of this batch.
            complete_fn (callable): A callback function called after
                training step.
        """
        # Batch can be a dict or a tuple of dicts (1 per model in the logic)
        for _, sm, rt in self._runtime_iterator(trainer.models):
            rt.train_pre_step(trainer, sm, batch_idx, batch)

        batch = self._entry_runtime.convert_batch(batch)

        outs = self._logic.train_step(
            trainer.models, trainer.optimizers, batch_idx, batch)

        if self._are_outs_deferred(outs):
            if len(self._ppe_modules) != 1:
                raise RuntimeError("Async mode is not supported in models "
                                   "splitted across different devices")
            for sn, sm, rt in self._runtime_iterator(trainer.models):
                self.pending_iters[sn].append(
                    _DeferredIteration(outs, batch_idx, batch, complete_fn))
                t_outs = self._get_deferred_outputs(self.pending_iters[sn][0])
                if t_outs is not None:
                    self._complete_train_step(
                        trainer, t_outs, False, sn, sm, rt)
        else:
            self._logic.train_step_optimizers(
                trainer.models, trainer.optimizers, batch_idx)
            complete_fn(batch_idx, outs)

    def eval_setup(
            self,
            evaluator: Evaluator,
            loader: Iterable[Any]
    ) -> None:
        """Called only once when starting a training run.
        When evaluator is not given, this method is not called.

        Args:
            evaluator (Evaluator): The evaluator.
            loader (torch.utils.data.DataLoader): The data loader.
        """
        for _, model in evaluator.models.items():
            model.eval()
        self._setup(evaluator.models, loader)

    def _complete_eval_step(
            self, evaluator: Evaluator, outs: Any, block: bool,
            sn: str, sm: torch.nn.Module, rt: 'BaseRuntime',
    ) -> None:
        # This call is deferred
        p_iter = self.pending_iters[sn][0]
        self.pending_iters[sn] = self.pending_iters[sn][1:]
        if len(self.pending_iters[sn]) == 0:
            del self.pending_iters[sn]
        p_iter.cback(p_iter.idx, outs, is_deferred=block)

    def eval_step(
            self,
            evaluator: Evaluator,
            batch_idx: int,
            batch: Any,
            complete_fn: Callable[[int, Any], None],
    ) -> None:
        """Evaluation iteration.

        Args:
            evaluator (Evaluator): The evaluator.
            batch_idx (int): Number of iterations already finished.
            batch (dict of torch.Tensor): Input tensors of this batch.
            complete_fn (callable): A callback function called after
                training step.
        """
        for _, sm, rt in self._runtime_iterator(evaluator.models):
            rt.eval_pre_step(evaluator, sm, batch_idx, batch)

        batch = self._entry_runtime.convert_batch(batch)

        outs = self._logic.eval_step(evaluator.models, batch_idx, batch)

        if self._are_outs_deferred(outs):
            if len(self._ppe_modules) != 1:
                raise RuntimeError("Async mode is not supported in models "
                                   "splitted across different devices")
            for sn, sm, rt in self._runtime_iterator(evaluator.models):
                self.pending_iters[sn].append(
                    _DeferredIteration(outs, batch_idx, batch, complete_fn))
                t_outs = self._get_deferred_outputs(self.pending_iters[sn][0])
                if t_outs is not None:
                    self._complete_eval_step(
                        evaluator, t_outs, False, sn, sm, rt)
        else:
            complete_fn(batch_idx, outs)

    def eval_post_step(
            self,
            evaluator: Evaluator,
            batch_idx: int,
            batch: Any,
            outputs: Any,
    ) -> None:
        """A method called after each evaluation step.

        Args:
            evaluator (Evaluator): The evaluator.
            batch_idx (int): Number of iterations already finished.
            batch (dict of torch.Tensor): Input tensors of this batch.
            complete_fn (callable): A callback function called after
                training step.
        """
        # Context: Evaluator
        # Called after eval_step.
        for _, sm, rt in self._runtime_iterator(evaluator.models):
            rt.eval_post_step(evaluator, sm, batch_idx, batch, outputs)
        for out in self._eval_report_keys:
            reporting.report({"val/{}".format(out): outputs[out]})

    def eval_loop_end(self, evaluator: Evaluator) -> None:
        """A method called after running all steps of the evaluation.

        Args:
            evaluator (Evaluator): The evaluator.
        """
        while self.pending_iters:
            for sn, sm, rt in self._runtime_iterator(evaluator.models):
                t_outs = self._get_deferred_outputs(
                    self.pending_iters[sn][0], True)
                self._complete_eval_step(
                    evaluator, t_outs, True, sn, sm, rt)

    def train_post_step(
            self,
            trainer: Trainer,
            batch_idx: int,
            batch: Any,
            outputs: Any
    ) -> None:
        """A method called after each training step.

        Args:
            trainer (Trainer): The trainer that calls this method.
            batch_idx (int): Number of iterations
            batch (dict of torch.Tensor): Input tensors of this batch.
            outputs (dict of torch.Tensor): Output tensors of this batch.
        """
        # Context: Trainer
        # Called after train_step.
        for _, sm, rt in self._runtime_iterator(trainer.models):
            rt.train_post_step(trainer, sm, batch_idx, batch, outputs)
        for out in self._train_report_keys:
            reporting.report({"train/{}".format(out): outputs[out]})
