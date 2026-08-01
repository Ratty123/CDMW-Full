#pragma once

#include <QQuickRhiItem>
#include <rhi/qrhi.h>

// The C++ half of the spike. Identical in behaviour to the Python version,
// which rendered correctly but never let the process exit: the PySide6 binding
// for QQuickRhiItemRenderer has no working ownership story. In C++ the renderer
// is owned by the item the way Qt intends, so teardown is Qt's problem again.

class RhiTriangleRenderer : public QQuickRhiItemRenderer
{
public:
    void initialize(QRhiCommandBuffer *cb) override;
    void synchronize(QQuickRhiItem *item) override;
    void render(QRhiCommandBuffer *cb) override;

private:
    QRhi *m_rhi = nullptr;
    std::unique_ptr<QRhiBuffer> m_vbuf;
    std::unique_ptr<QRhiBuffer> m_ubuf;
    std::unique_ptr<QRhiShaderResourceBindings> m_srb;
    std::unique_ptr<QRhiGraphicsPipeline> m_pipeline;
    float m_angle = 0.0f;
    bool m_spinning = true;
    class RhiTriangle *m_item = nullptr;
};

class RhiTriangle : public QQuickRhiItem
{
    Q_OBJECT
    Q_PROPERTY(bool spinning READ spinning WRITE setSpinning NOTIFY spinningChanged)
    QML_ELEMENT

public:
    explicit RhiTriangle(QQuickItem *parent = nullptr);

    QQuickRhiItemRenderer *createRenderer() override;

    bool spinning() const { return m_spinning; }
    void setSpinning(bool spinning);

    // How many frames the render thread has actually recorded. The spike reads
    // this from QML so the proof does not depend on anyone watching the window.
    Q_INVOKABLE int frameCount() const { return m_frameCount.loadRelaxed(); }
    void noteFrame() { m_frameCount.fetchAndAddRelaxed(1); }

signals:
    void spinningChanged();

private:
    bool m_spinning = true;
    QAtomicInt m_frameCount = 0;
};
