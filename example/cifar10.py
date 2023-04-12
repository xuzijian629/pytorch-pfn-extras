import argparse
import tempfile
from typing import Dict

import pytorch_pfn_extras as ppe
import pytorch_pfn_extras.training.extensions as ext
import pytorch_pfn_extras.training.triggers as triggers
import torch
import torch.nn as nn
from pytorch_pfn_extras.engine import create_evaluator, create_trainer
from torch.utils.data import DataLoader
from torchvision import transforms
from torchvision.datasets import CIFAR10
from torchvision.models.convnext import ConvNeXt, convnext_small


class TrainerModel(nn.Module):
    def __init__(self, model: ConvNeXt, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.model = model
        self.criterion = nn.CrossEntropyLoss()

    def forward(self, x: torch.Tensor, y: torch.Tensor) -> Dict[str, torch.Tensor]:
        out = self.model.forward(x)
        loss = self.criterion.forward(out, y)
        ppe.reporting.report({"train/loss": loss.item()})
        return {"loss": loss}


class EvaluatorModel(nn.Module):
    def __init__(self, model: ConvNeXt, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.model = model
        self.criterion = nn.CrossEntropyLoss()

    def forward(self, x: torch.Tensor, y: torch.Tensor) -> None:
        out = self.model.forward(x)
        loss = self.criterion.forward(out, y)
        acc = (out.argmax(axis=1) == y).sum() / len(y)
        ppe.reporting.report(
            {
                "val/loss": loss.item(),
                "val/accuracy": acc.item(),
            }
        )


def main():
    parser = argparse.ArgumentParser(
        description="Train a ConvNeXt model on CIFAR-10 dataset "
        "using PyTorch and pytorch-pfn-extras.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--gpu", "-g", type=int, default=0, help="GPU ID to use for training"
    )
    parser.add_argument(
        "--epoch", "-e", type=int, default=20, help="Number of training epochs"
    )
    parser.add_argument(
        "--out",
        "-o",
        type=str,
        default="output",
        help="Output directory to save the results",
    )
    parser.add_argument(
        "--n-retains", "-n", type=int, default=5, help="Number of snapshots to retain"
    )
    parser.add_argument(
        "--num-worker",
        type=int,
        default=0,
        help="Number of worker threads for data loading",
    )
    parser.add_argument(
        "--cifar-dir",
        type=str,
        default=None,
        help="Directory for CIFAR-10 dataset; downloads dataset if not provided",
    )
    args = parser.parse_args()

    device = "cuda:{}".format(args.gpu)
    if args.cifar_dir is None:
        tmp_dir = tempfile.TemporaryDirectory()
        cifar_dir = tmp_dir.name
    else:
        cifar_dir = args.cifar_dir

    train = CIFAR10(
        cifar_dir,
        download=True,
        train=True,
        transform=transforms.Compose(
            [transforms.RandomHorizontalFlip(p=1.0), transforms.ToTensor()]
        ),
    )
    val = CIFAR10(
        cifar_dir, download=True, train=False, transform=transforms.ToTensor()
    )

    train_loader = DataLoader(
        train, batch_size=64, num_workers=args.num_worker, shuffle=True
    )
    val_loader = DataLoader(
        val, batch_size=64, num_workers=args.num_worker, shuffle=False
    )

    model = convnext_small(num_classes=10)
    trainer_model = TrainerModel(model=model)
    evaluator_model = EvaluatorModel(model=model)
    optimizer = torch.optim.Adam(trainer_model.parameters(), lr=1e-3)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer=optimizer, T_max=args.epoch
    )

    trainer = create_trainer(
        models=ppe.to(trainer_model, device),
        optimizers=optimizer,
        max_epochs=args.epoch,
        extensions=[
            ext.LogReport(),
            ext.ProgressBar(),
            ext.PrintReport(
                ["epoch", "iteration", "train/loss", "val/loss", "val/accuracy", "lr"]
            ),
            ppe.training.ExtensionEntry(
                ext.snapshot(n_retains=args.n_retains, autoload=True),
                trigger=(1, "epoch"),
            ),
            ppe.training.ExtensionEntry(
                ext.snapshot(target=model, filename="best_model", n_retains=1),
                trigger=triggers.MaxValueTrigger(
                    key="val/accuracy", trigger=(1, "epoch")
                ),
            ),
            ppe.training.ExtensionEntry(
                ext.observe_lr(optimizer),
                trigger=(1, "epoch"),
            ),
            ppe.training.ExtensionEntry(
                ext.LRScheduler(scheduler),
                trigger=(1, "epoch"),
            ),
        ],
        out_dir=args.out,
        stop_trigger=triggers.EarlyStoppingTrigger(
            check_trigger=(1, "epoch"),
            monitor="val/accuracy",
            mode="max",
            patience=5,
            max_trigger=(args.epoch, "epoch"),
        ),
        evaluator=create_evaluator(
            ppe.to(evaluator_model, device),
            progress_bar=True,
            device=device,
        ),
        device=device,
    )

    trainer.run(train_loader=train_loader, val_loader=val_loader)


if __name__ == "__main__":
    main()
