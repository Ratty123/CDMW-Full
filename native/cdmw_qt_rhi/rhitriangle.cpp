#include "rhitriangle.h"

#include <QFile>
#include <QMatrix4x4>

namespace {

// position(x,y) + colour(r,g,b), interleaved, 5 floats per vertex.
constexpr float kVertices[] = {
    0.0f,  0.6f,  1.00f, 0.25f, 0.25f,
   -0.6f, -0.5f,  0.25f, 1.00f, 0.35f,
    0.6f, -0.5f,  0.35f, 0.45f, 1.00f,
};
constexpr int kUniformBufferSize = 64; // one mat4

QShader loadShader(const QString &path)
{
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly))
        return {};
    return QShader::fromSerialized(file.readAll());
}

} // namespace

RhiTriangle::RhiTriangle(QQuickItem *parent)
    : QQuickRhiItem(parent)
{
    setAlphaBlending(true);
}

void RhiTriangle::setSpinning(bool spinning)
{
    if (m_spinning == spinning)
        return;
    m_spinning = spinning;
    emit spinningChanged();
    update();
}

QQuickRhiItemRenderer *RhiTriangle::createRenderer()
{
    // Returned to Qt, which owns it from here. This is the part the Python
    // binding gets wrong in both directions.
    return new RhiTriangleRenderer;
}

void RhiTriangleRenderer::synchronize(QQuickRhiItem *item)
{
    // Runs with the main thread blocked, so this is the one safe place to copy
    // state between the item and the renderer.
    auto *triangle = static_cast<RhiTriangle *>(item);
    m_spinning = triangle->spinning();
    // Held so render(), which runs on the render thread with no access to the
    // item, can count the frames it actually records.
    m_item = triangle;
}

void RhiTriangleRenderer::initialize(QRhiCommandBuffer *cb)
{
    if (m_rhi != rhi()) {
        m_rhi = rhi();
        m_pipeline.reset();
    }
    if (m_pipeline)
        return;

    m_vbuf.reset(m_rhi->newBuffer(QRhiBuffer::Immutable, QRhiBuffer::VertexBuffer,
                                  sizeof(kVertices)));
    m_vbuf->create();

    m_ubuf.reset(m_rhi->newBuffer(QRhiBuffer::Dynamic, QRhiBuffer::UniformBuffer,
                                  kUniformBufferSize));
    m_ubuf->create();

    m_srb.reset(m_rhi->newShaderResourceBindings());
    m_srb->setBindings({
        QRhiShaderResourceBinding::uniformBuffer(
            0,
            QRhiShaderResourceBinding::VertexStage | QRhiShaderResourceBinding::FragmentStage,
            m_ubuf.get()),
    });
    m_srb->create();

    QRhiVertexInputLayout layout;
    layout.setBindings({ { 5 * sizeof(float) } });
    layout.setAttributes({
        { 0, 0, QRhiVertexInputAttribute::Float2, 0 },
        { 0, 1, QRhiVertexInputAttribute::Float3, 2 * sizeof(float) },
    });

    m_pipeline.reset(m_rhi->newGraphicsPipeline());
    m_pipeline->setShaderStages({
        { QRhiShaderStage::Vertex, loadShader(QStringLiteral(":/shaders/tri.vert.qsb")) },
        { QRhiShaderStage::Fragment, loadShader(QStringLiteral(":/shaders/tri.frag.qsb")) },
    });
    m_pipeline->setVertexInputLayout(layout);
    m_pipeline->setShaderResourceBindings(m_srb.get());
    m_pipeline->setRenderPassDescriptor(renderTarget()->renderPassDescriptor());
    m_pipeline->create();

    QRhiResourceUpdateBatch *batch = m_rhi->nextResourceUpdateBatch();
    batch->uploadStaticBuffer(m_vbuf.get(), kVertices);
    cb->resourceUpdate(batch);
}

void RhiTriangleRenderer::render(QRhiCommandBuffer *cb)
{
    if (!m_pipeline)
        return;

    QRhiRenderTarget *target = renderTarget();
    const QSize size = target->pixelSize();

    if (m_spinning)
        m_angle += 2.0f;

    const float aspect = float(size.width()) / float(qMax(1, size.height()));
    QMatrix4x4 projection;
    projection.ortho(-aspect, aspect, -1.0f, 1.0f, -1.0f, 1.0f);
    QMatrix4x4 mvp = m_rhi->clipSpaceCorrMatrix() * projection;
    mvp.rotate(m_angle, 0.0f, 0.0f, 1.0f);

    QRhiResourceUpdateBatch *batch = m_rhi->nextResourceUpdateBatch();
    batch->updateDynamicBuffer(m_ubuf.get(), 0, kUniformBufferSize, mvp.constData());

    cb->beginPass(target, QColor(0, 0, 0, 0), { 1.0f, 0 }, batch);
    cb->setGraphicsPipeline(m_pipeline.get());
    cb->setViewport({ 0, 0, float(size.width()), float(size.height()) });
    cb->setShaderResources();
    const QRhiCommandBuffer::VertexInput vertexInput(m_vbuf.get(), 0);
    cb->setVertexInput(0, 1, &vertexInput);
    cb->draw(3);
    cb->endPass();

    if (m_item)
        m_item->noteFrame();
    if (m_spinning)
        update();
}
