import numpy as np
import torch
from oceanembed.model import OceanNet, masked_loss
from oceanembed.inference import predict_day

torch.set_num_threads(2)


def test_temporal_causality():
    torch.manual_seed(4)
    m = OceanNet(8).eval()
    x = torch.randn(1, 9, 21, 8, 8)
    a = m.encode_sequence(x)
    x[:, 5:] += 100
    b = m.encode_sequence(x)
    torch.testing.assert_close(a[:, :5], b[:, :5])


def test_shape_mask_and_gradient():
    m = OceanNet(8)
    x = torch.randn(2, 7, 21, 8, 8)
    p = torch.ones(2, 15, 8, 8) * 20
    s = torch.zeros(2, 4, 8, 8)
    y = p.clone()
    y[:, :, 0, :] = float("nan")
    pred = m(x, p, s)
    assert pred.shape == y.shape
    loss = masked_loss(pred, y)
    loss.backward()
    assert torch.isfinite(loss)
    assert m.spatial[0].weight.grad.abs().sum() > 0


def test_tiling_and_checkpoint(tmp_path):
    torch.manual_seed(1)
    m = OceanNet(8).eval()
    x = torch.randn(1, 7, 21, 20, 24)
    p = torch.randn(1, 15, 20, 24)
    s = torch.randn(1, 4, 20, 24)
    with torch.no_grad():
        a = m(x, p, s).numpy()[0]
    b = predict_day(m, x.numpy()[0], p.numpy()[0], s.numpy()[0], tile=8)
    np.testing.assert_allclose(a, b, atol=2e-6, rtol=2e-5)
    path = tmp_path / "weights.pt"
    torch.save(m.state_dict(), path)
    n = OceanNet(8).eval()
    n.load_state_dict(torch.load(path, weights_only=True, map_location="cpu"))
    with torch.no_grad():
        torch.testing.assert_close(m(x, p, s), n(x, p, s))


def test_tiny_batch_overfits():
    torch.manual_seed(5)
    m = OceanNet(8)
    x = torch.randn(1, 7, 21, 8, 8)
    p = torch.ones(1, 15, 8, 8) * 20
    s = torch.zeros(1, 4, 8, 8)
    y = p + 0.7
    optimizer = torch.optim.Adam(m.parameters(), lr=0.01)
    initial = masked_loss(m(x, p, s), y).item()
    for _ in range(35):
        optimizer.zero_grad()
        loss = masked_loss(m(x, p, s), y)
        loss.backward()
        optimizer.step()
    assert masked_loss(m(x, p, s), y).item() < initial * 0.3
