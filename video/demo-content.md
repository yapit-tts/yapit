# Gradient Descent in 5 Minutes

Optimization is the backbone of machine learning. Every model you've ever used — from linear regression to GPT — learns by minimizing a loss function[^1]. The most common way to do that is **gradient descent**.

## The Core Idea

Given a function $f(\theta)$, we want to find the parameters $\theta$ that minimize it. The gradient $\nabla f(\theta)$ points in the direction of steepest *increase*, so we step in the opposite direction:

$$\theta_{t+1} = \theta_t - \eta \nabla f(\theta_t)$$

where $\eta$ is the learning rate — too large and you overshoot, too small and you never converge.

> [!BLUE] Key Insight
> The gradient tells you the slope. You always walk downhill. That's it — the rest is engineering.

## Variants That Matter

| Method | Adapts LR? | Memory | Best for |
|--------|-----------|--------|----------|
| SGD | No | $O(1)$ | Convex problems |
| SGD + Momentum | No | $O(n)$ | Deep networks |
| Adam | Yes | $O(2n)$ | General default |
| LBFGS | Yes | $O(mn)$ | Small models |

**Adam**[^2] adapts the learning rate per parameter using running averages of the first and second moments:

$$\hat{m}_t = \frac{m_t}{1 - \beta_1^t}, \quad \hat{v}_t = \frac{v_t}{1 - \beta_2^t}, \quad \theta_t = \theta_{t-1} - \frac{\eta \hat{m}_t}{\sqrt{\hat{v}_t} + \epsilon}$$

> [!GREEN] Why Adam Dominates
> It handles sparse gradients, non-stationary objectives, and requires almost no tuning. Start with $\eta = 3 \times 10^{-4}$ and only switch if you have a reason to.

> [!PURPLE] Common Pitfall
> ~~Setting the learning rate by gut feeling.~~ Use a learning rate finder: sweep $\eta$ from $10^{-7}$ to $1$, plot the loss, pick the steepest descent point.

## What Can Go Wrong

- **Vanishing gradients** in deep networks — solved by residual connections and careful initialization
- **Saddle points** in high dimensions — less of a problem than local minima, despite the intuition
- **Learning rate too high** — loss explodes. ~~Too low — training stalls forever.~~ Too low — training stalls, but at least it doesn't diverge

The surprising thing about modern optimization: simple methods, applied at scale, tend to win.

[^1]: A loss function measures how wrong the model's predictions are. Lower is better.
[^2]: Kingma & Ba, "Adam: A Method for Stochastic Optimization", 2015.
