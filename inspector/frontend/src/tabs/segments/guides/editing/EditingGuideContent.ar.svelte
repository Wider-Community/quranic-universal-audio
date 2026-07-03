<script lang="ts">
    /**
     * Arabic sibling of `EditingGuideContent.svelte` — the illustrated "Editing
     * guide" body. Selected by `AccordionGuideModal` when the locale is `ar`
     * (mirrors the `.ar.guide.ts` / `overview.ar.md` parallel-source convention).
     * Only the prose differs; the shared `MockSegCard` / `ValActionMock` are
     * locale-aware, so their button labels already read Arabic here.
     */
    import MockSegCard from './MockSegCard.svelte';
    import { synthPeaks } from './synth-peaks';
    import ValActionMock from './ValActionMock.svelte';

    const wave = synthPeaks(150, 7);
    const waveB = synthPeaks(150, 19);
</script>

<div class="eg-root">
    <div class="eg-banner">📖 قراءة إلزامية — جولة سريعة في التحرير قبل أن تبدأ.</div>

    <!-- What is a segment -->
    <p>
        <strong>المقطع</strong> هو الوحدة الأساسية التي ينتجها خط المعالجة. يتتبّع الوقفات (حيث
        يتوقف القارئ) ليقسّم التسجيل إلى أجزاء، ثم يطابق كل جزء بكلمات القرآن التي يظن أنها تُليت.
    </p>
    <p>وإليك ما تعرضه بطاقة المقطع الواحدة:</p>
    <div class="eg-card-frame">
        <MockSegCard peaks={wave} placeholder />
    </div>

    <!-- Adjust -->
    <h3 class="eg-h">اضبط — تصحيح وقتَي البداية والنهاية</h3>
    <p>استخدم <strong>اضبط</strong> حين تكون الكلمات صحيحة لكن التوقيت غير دقيق.</p>
    <div class="eg-card-frame">
        <MockSegCard peaks={wave} emphasize={['adjust', 'time']} />
    </div>
    <p>بمجرد دخولك وضع الضبط، تتحوّل البطاقة إلى التشذيب:</p>
    <div class="eg-card-frame">
        <MockSegCard peaks={wave} mode="adjust" />
    </div>
    <p class="eg-note">
        الخط <span class="eg-ink-start">الأخضر</span> هو البداية، والخط
        <span class="eg-ink-end">الأحمر</span> هو النهاية. حرّكهما بثلاث طرق: اسحب الخط على المخطط
        الموجي، أو انقر أزرار <strong>‹ ›</strong> للتحريك الدقيق، أو اكتب وقتًا محددًا في حقل الوقت.
        اضغط <strong>تطبيق</strong> للإبقاء عليه، أو <strong>إلغاء</strong> لإسقاطه.
    </p>

    <!-- Split -->
    <h3 class="eg-h">قسِّم — تقطيع مقطع واحد إلى اثنين</h3>
    <p>استخدم <strong>قسِّم</strong> حين يحتوي مقطع واحد فعليًّا على جزأين منفصلين.</p>
    <div class="eg-card-frame">
        <MockSegCard peaks={wave} emphasize={['split']} />
    </div>
    <p>دخول وضع التقسيم يُسقِط مؤشرًا <span class="eg-ink-split">أصفر</span> عند موضع القطع:</p>
    <div class="eg-card-frame">
        <MockSegCard peaks={wave} mode="split" compact />
    </div>
    <p class="eg-note">
        حرّك المؤشر (بالسحب أو بأزرار <strong>‹ ›</strong>)، واستمع لكل جانب عبر
        <strong>L</strong> / <strong>R</strong>، ثم اضغط <strong>قسِّم</strong>. وحين يعبر المقطع
        حدَّ آية أو يحوي عبارة مكررة، يصبح الزر <strong>تقسيم تلقائي</strong> ويضع القطوع مسبقًا لك —
        فتؤكّدها وتعدّلها قليلًا عند الحاجة.
    </p>

    <p class="eg-note">
        في وضعَي الضبط والتقسيم، يمكنك تكبير أي موضع على المخطط الموجي بعجلة الفأرة لمزيد من الدقة.
    </p>

    <!-- Edit Ref -->
    <h3 class="eg-h">حرِّر المرجع — تغيير الكلمات التي يغطّيها</h3>
    <p>
        استخدم <strong>حرِّر المرجع</strong> حين يكون التوقيت سليمًا لكن الكلمات المطابَقة خاطئة.
        يمكنك النقر على نص المرجع نفسه أو على زر <strong>حرِّر المرجع</strong>.
    </p>
    <div class="eg-card-frame">
        <MockSegCard peaks={wave} emphasize={['editref', 'ref']} />
    </div>
    <p>يتحوّل المرجع إلى حقل إدخال صغير تكتب فيه:</p>
    <div class="eg-card-frame">
        <MockSegCard peaks={wave} mode="reference" />
    </div>
    <p class="eg-note">
        تُكتب المراجع بصيغة <strong>سورة:آية:كلمة - سورة:آية:كلمة (<code>s:v:w - s:v:w</code>)</strong>.
        اختصارات: <code>s:v</code> تحدد الآية كاملة، و<code>s:v:w</code> تحدد تلك الكلمة وحدها. اضغط
        <strong>Enter</strong> للتأكيد، و<strong>Esc</strong> للإلغاء.

        وإدخال مرجع فارغ يجعله محاذاة فاشلة بنص فارغ (مفيد أحيانًا، انظر دليل المحاذاة الفاشلة).
    </p>

    <!-- Merge -->
    <h3 class="eg-h">دمج ↑ / دمج ↓ — الوصل بمقطع مجاور</h3>
    <p>
        استخدم <strong>الدمج</strong> حين يُقسَّم مقطع تقسيمًا مفرطًا. <strong>دمج ↑</strong> يصل هذا
        المقطع بالذي فوقه؛ و<strong>دمج ↓</strong> يصله بالذي تحته. فيصيران مقطعًا واحدًا.
    </p>
    <div class="eg-card-frame">
        <MockSegCard peaks={wave} emphasize={['merge-prev', 'merge-next']} />
    </div>

    <!-- Delete -->
    <h3 class="eg-h">احذف — إزالة مقطع</h3>
    <p>
        استخدم <strong>احذف</strong> لمقطع لا ينبغي أن يوجد — صمت، أو ضوضاء، أو كلام غير قرآني، أو
        مشكلات صوتية غريبة. يُزال من القائمة (ويمكنك دائمًا التراجع عنه لاحقًا).
    </p>
    <div class="eg-card-frame">
        <MockSegCard peaks={waveB} emphasize={['delete']} />
    </div>

    <!-- Special ops -->
    <h3 class="eg-h">اختصاران على بطاقات التحقق</h3>
    <p>
        حين تُبلِّغ اللوحة عن مشكلة، تتيح بعض البطاقات إصلاحًا بنقرة واحدة:
    </p>
    <div class="eg-special">
        <div class="eg-special-col">
            <ValActionMock kind="autofill" />
            <p class="eg-note">
                <strong>الملء التلقائي</strong> يملأ لك <em>كلمة ناقصة</em>.
            </p>
        </div>
        <div class="eg-special-col">
            <ValActionMock kind="ignore" />
            <p class="eg-note">
                <strong>تجاهل</strong> يصرف تنبيهًا فحصته وقررت أنه سليم، لذلك المقطع وحده. فيتوقف
                ظهور التحذير لتلك الفئة.
            </p>
        </div>
    </div>

    <!-- What to edit -->
    <h3 class="eg-h">ماذا تُحرِّر</h3>
    <p>
        الحد الأدنى هو تصحيح جميع أخطاء فئات التحقق (وسيخبرك نموذج «تعليم الجاهزية» متى تُزال). وبما
        أنه يتعذّر الإبلاغ الآلي عن كل خطأ محتمل، يُستحسن إجراء فحوص إضافية، مثل:
    </p>
    <div style="margin-inline-start: 3em;">
        <ul>
            <li>الاستماع إلى سور كاملة (عبر منتقي السور) والتأكد من خلوّ حدود المقاطع والمراجع من المشكلات</li>
            <li>التحقق من أي مشكلات في جودة الصوت</li>
            <li>رفع عتبة الثقة المنخفضة فوق الافتراضي ومراجعة تلك المقاطع أيضًا</li>
            <li>استخدام المرشّحات للبحث عن مقاطع قد تكون إشكالية (مثل كلمة أو كلمتين، أو كلمات كثيرة، أو مقاطع قصيرة/طويلة المدة جدًّا، إلخ)</li>
        </ul>
    </div>

    <!-- Saving & history -->
    <h3 class="eg-h">الحفظ، والتراجع عن أي شيء</h3>
    <p>
        تُحفظ تعديلاتك أولًا بأول. مع تفعيل <strong>الحفظ التلقائي</strong> تُحفظ لك؛ ويمكنك أيضًا
        الضغط على <strong>حفظ</strong> بنفسك في أي وقت. لا شيء يُقفل نهائيًّا — تسرد لوحة
        <strong>السجل</strong> كل تعديل، ويمكنك <strong>التراجع</strong> عن أيٍّ منها. ويمكنك ترشيح
        السجل حسب نوع التعديل أو فئة التحقق للعثور على تغيير والتحقق منه مجددًا.
    </p>

    <p>
        يمكنك دائمًا الاطلاع على سجل قارئ منشور لفهم التعديلات وأنواع المشكلات الشائعة فهمًا أفضل.
        ويُستحسن أيضًا مراجعة تعديلاتك بدقة، إما من السجل بعد الانتهاء، أو بإيقاف الحفظ التلقائي
        واستخدام الحفظ اليدوي أحيانًا لمراجعة التغييرات المُجهَّزة قبل تأكيد الحفظ.
    </p>
</div>
