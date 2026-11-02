"""Shared CNN, left-padded temporal convolution and prior-conditioned direct head."""

import torch
from torch import nn
from torch.nn import functional as F


class OceanNet(nn.Module):
    def __init__(self, width=32, temporal=True):
        super().__init__()
        self.width = width
        self.temporal = temporal
        # No BatchNorm: training statistics must not mix future sequence frames.
        self.spatial = nn.Sequential(
            nn.Conv2d(21, width, 3, padding=1),
            nn.GELU(),
            nn.Conv2d(width, width, 3, padding=1),
            nn.GELU(),
        )
        self.t1 = nn.Conv1d(width, width, 3, dilation=1)
        self.t2 = nn.Conv1d(width, width, 3, dilation=2)
        self.t3 = nn.Conv1d(width, width, 3, dilation=4)
        self.decoder = nn.Sequential(
            nn.Conv2d(width + 15 + 4, width, 3, padding=1),
            nn.GELU(),
            nn.Conv2d(width, 15, 1),
        )

    def encode_sequence(self, x):
        b, l, c, h, w = x.shape
        s = self.spatial(x.reshape(b * l, c, h, w)).reshape(b, l, self.width, h, w)
        if not self.temporal:
            return s
        t = s.permute(0, 3, 4, 2, 1).reshape(b * h * w, self.width, l)
        t = F.gelu(self.t1(F.pad(t, (2, 0))))
        t = F.gelu(self.t2(F.pad(t, (4, 0))))
        t = F.gelu(self.t3(F.pad(t, (8, 0))))
        return t.reshape(b, h, w, self.width, l).permute(0, 4, 3, 1, 2)

    def forward(self, x, prior, static):
        last = self.encode_sequence(x)[:, -1]
        residual = self.decoder(torch.cat([last, prior / 30, static], dim=1))
        return prior + residual


def masked_loss(pred, target):
    valid = torch.isfinite(target)
    safe = torch.nan_to_num(target)
    # Equal weight per supported depth, not per wet cell across all depths.
    counts = valid.sum((0, 2, 3))
    supported = counts > 0
    if not supported.any():
        raise ValueError("No valid target values in batch")
    depth_error = ((pred - safe).square() * valid).sum((0, 2, 3)) / counts.clamp_min(1)
    return depth_error[supported].mean()
