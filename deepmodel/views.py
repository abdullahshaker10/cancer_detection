from basicapp.models import Patient
from skimage.feature import peak_local_max
from skimage.morphology import watershed
from scipy import ndimage
import imutils
import scipy

from pylab import *
import zipfile
import pydicom  # for reading dicom files
import os  # for doing directory operations
import cv2
import numpy as np
import tensorflow as tf
from django.shortcuts import redirect, render
from django.conf import settings
from django.views.generic import CreateView
from .forms import SlicesForm, SlicesFormdl, DeepModelForm
from django.urls import reverse_lazy
from .models import DeepModel
import pdb


class UploadModel(CreateView):
    template_name = 'upload_model.html'
    form_class = DeepModelForm
    success_url = reverse_lazy('login')


def index(request):
    patients = Patient.objects.all()
    return render(request, 'basicapp/patient_list.html', {'patients': patients})


def get_slice_dl(request, patient_id, slices_num, message):
    if request.method == 'POST':
        form = SlicesFormdl(request.POST)
        if form.is_valid():
            slice_num = form.cleaned_data['slice_num']
    elif request.method == 'GET':
        form = SlicesForm()
        slice_num = 0

    path1 = []
    path2 = []
    for slice in range(int(slice_num), int(slices_num)):
        # path1.append(('DICOM/' + str(patient_id) + '/DL/original/' + str(slice) + '.png'))
        path2.append(('DICOM/' + str(patient_id) + '/DL/tumors/' + str(slice) + '.png'))

    # pdb.set_trace()

    return render(request, 'slices_dl.html', {
        'tumor_slices': path2,
        'patient_id': patient_id,
        'sent': message
    })


def load_scan(patient_id):
    # reading data
    # current path of app 'deepmodel'
    BASE = settings.BASE_DIR
    DICOM = settings.STATICFILES_DIRS[1]

    # get patient
    patient = Patient.objects.get(id=patient_id)

    # get PATIENT_DICOM of patient
    file = patient.PATIENT_DICOM

    # path of target directory to unzip
    target = os.path.join(DICOM, str(patient.id))

    # unzip directory
    with zipfile.ZipFile(file.path, 'r') as zip:
        path = zip.extractall(target)
    # get slices
    slices = []
    images = []
    target = target + "/PATIENT_DICOM"
    slices = [pydicom.read_file(target + '/' + s) for s in os.listdir(target)]

    slices.sort(key=lambda x: int(x.InstanceNumber))

    try:
        slice_thickness = np.abs(slices[0].ImagePositionPatient[2] - slices[1].ImagePositionPatient[2])
    except:
        slice_thickness = np.abs(slices[0].SliceLocation - slices[1].SliceLocation)

    for s in slices:
        s.SliceThickness = slice_thickness
        # pdb.set_trace()

    return slices


# returns the hounse fied unit of slices
def get_pixels_hu(scans):
    image = np.stack([s.pixel_array for s in scans])
    # Convert to int16 (from sometimes int16),
    # should be possible as values should always be low enough (<32k)
    image = image.astype(np.int16)

    # Set outside-of-scan pixels to 1
    # The intercept is usually -1024, so air is approximately 0
    image[image == -2000] = 0

    # Convert to Hounsfield units (HU)
    intercept = scans[0].RescaleIntercept
    slope = scans[0].RescaleSlope

    if slope != 1:
        image = slope * image.astype(np.float64)
        image = image.astype(np.int16)

    image += np.int16(intercept)
    return np.array(image, dtype=np.int16)


def get_pixels_hu_DL(slices):
    image = np.stack([s.pixel_array for s in slices])

    # Convert to int16 (from sometimes int16),
    # should be possible as values should always be low enough (<32k)

    image = image.astype(np.int16)

    # Set outside-of-scan pixels to 0
    # The intercept is usually -1024, so air is approximately 0
    image[image == -2000] = 0

    # Convert to Hounsfield units (HU)
    for slice_number in range(len(slices)):

        intercept = slices[slice_number].RescaleIntercept
        slope = slices[slice_number].RescaleSlope

        if slope != 1:
            image[slice_number] = slope * image[slice_number].astype(np.float64)
            image[slice_number] = image[slice_number].astype(np.int16)

        image[slice_number] += np.int16(intercept)

    return np.array(image, dtype=np.int16)


def crop(img):
    return img[80:400, 30:350]


def image_histogram_equalization(image, number_bins=256):
    # from http://www.janeriksolem.net/2009/06/histogram-equalization-with-python-and.html

    # get image histogram
    image_histogram, bins = np.histogram(image.flatten(), number_bins, density=True)
    cdf = image_histogram.cumsum()  # cumulative distribution function
    cdf = 255 * cdf / cdf[-1]  # normalize

    # use linear interpolation of cdf to find new pixel values
    image_equalized = np.interp(image.flatten(), bins[:-1], cdf)

    return image_equalized.reshape(image.shape)


def threshold(img):
    img = img.astype(np.uint8)

    th2 = cv2.adaptiveThreshold(img, 255, cv2.ADAPTIVE_THRESH_MEAN_C, \
                                cv2.THRESH_BINARY, 117, 7)

    return th2


def erode(img):
    kernel = np.ones((5, 5), np.uint8)
    img = cv2.morphologyEx(img, cv2.MORPH_CLOSE, kernel)
    kernel = np.ones((6, 6), np.uint8)

    img = cv2.morphologyEx(img, cv2.MORPH_OPEN, kernel, iterations=5)
    return img


def countores(img):
    objects = np.zeros([img.shape[0], img.shape[1], 3], 'uint8')
    contours, hierarchy = cv2.findContours(img, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    color = (255, 255, 255)
    c = max(contours, key=cv2.contourArea)
    # print(cv2.contourArea(c))
    cv2.drawContours(objects, [c], -1, color, -1)

    if cv2.contourArea(c) > 60000:
        return np.zeros([img.shape[0], img.shape[1]], 'uint8')

    objects = cv2.cvtColor(objects, cv2.COLOR_BGR2GRAY)

    return objects


def make_mask(largest_shape, imgs_to_process):
    # largest_shape = cv2.cvtColor(largest_shape, cv2.COLOR_BGR2GRAY)
    ret, mask = cv2.threshold(largest_shape, 120, 255, cv2.THRESH_BINARY)
    new_mask = np.zeros([imgs_to_process[0].shape[0], imgs_to_process[0].shape[1]], 'uint8')
    # print(new_mask)
    new_mask[80:400, 30:350] = mask

    return new_mask


def segement_liver(img, mask):
    return cv2.bitwise_and(img, mask)


def find_tumor(image):
    image = image.astype(np.uint8)

    image = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)

    shifted = cv2.pyrMeanShiftFiltering(image, 21, 51)

    # convert the mean shift image to grayscale, then apply
    # Otsu's thresholding
    gray = cv2.cvtColor(shifted, cv2.COLOR_BGR2GRAY)
    thresh = cv2.threshold(gray, 0, 255,
                           cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]

    # compute the exact Euclidean distance from every binary
    # pixel to the nearest zero pixel, then find peaks in this
    # distance map
    D = ndimage.distance_transform_edt(thresh)
    localMax = peak_local_max(D, indices=False, min_distance=15,
                              labels=thresh)

    # perform a connected component analysis on the local peaks,
    # using 8-connectivity, then appy the Watershed algorithm
    markers = ndimage.label(localMax, structure=np.ones((3, 3)))[0]
    labels = watershed(-D, markers, mask=thresh)

    labels = labels.astype(np.uint8)

    #    print((np.unique(labels)[1]))

    # loop over the unique labels returned by the Watershed
    # algorithm
    for label in np.unique(labels):
        # if the label is zero, we are examining the 'background'
        # so simply ignore it
        if label == 0:
            continue

        # otherwise, allocate memory for the label region and draw
        # it on the mask
        mask = np.zeros(gray.shape, dtype="uint8")
        mask[labels == label] = 255

        # detect contours in the mask and grab the largest one
        cnts = cv2.findContours(mask.copy(), cv2.RETR_EXTERNAL,
                                cv2.CHAIN_APPROX_SIMPLE)
        cnts = imutils.grab_contours(cnts)
        c = max(cnts, key=cv2.contourArea)
        print(np.average(c))

        if 140 < np.average(c) <= 160.0 or 200 <= np.average(c) <= 205:
            # draw a circle enclosing the object
            ((x, y), r) = cv2.minEnclosingCircle(c)
            cv2.circle(image, (int(x), int(y)), int(r), (0, 255, 0), 2)

    return image


def make_img_proces_folders(patient_id, path):
    if not os.path.exists(path + '/' + 'image_proces'):
        os.mkdir(path + '/' + 'image_proces')
        processed_path = os.path.join(path, 'image_proces')
        # pdb.set_trace()
        os.mkdir(processed_path + '/' + 'original')
        os.mkdir(processed_path + '/' + 'tumors')

        # os.mkdir(processed_path + '/' + 'croped')
        # os.mkdir(processed_path + '/' + 'enhanced')
        # os.mkdir(processed_path + '/' + 'threshold')
        # os.mkdir(processed_path + '/' + 'eroded')
        # os.mkdir(processed_path + '/' + 'largest_shape')
        # os.mkdir(processed_path + '/' + 'masks')
        # os.mkdir(processed_path + '/' + 'segement')
        # os.mkdir(processed_path + '/' + 'tumors')


def Examine_img(request, patient_id):
    BASE = settings.BASE_DIR
    DICOM = settings.STATICFILES_DIRS[1]

    path = os.path.join(DICOM, str(patient_id))

    scans = load_scan(patient_id)
    imgs_to_process = get_pixels_hu(scans)
    make_img_proces_folders(patient_id, path)
    slices_num = len(imgs_to_process)
    patient_id = patient_id
    return render(request, 'slices.html', {'slices_num': slices_num,
                                           'patient_id': patient_id})


def get_slice_num(request):
    if request.method == 'POST':
        form = SlicesForm(request.POST)
        if form.is_valid():
            slice = form.cleaned_data['slice_num']
            patient_id = form.cleaned_data['patient_id']
            return redirect('deepmodel:start', slice=slice, patient_id=patient_id)
        else:
            form = SlicesForm()


def normalize(image):
    MIN_BOUND = -200.0
    MAX_BOUND = 500.0
    image = (image - MIN_BOUND) / (MAX_BOUND - MIN_BOUND)
    image[image > 1] = 1.
    image[image < 0] = 0.
    return image


# resample voxels to 1mm,1mm,1mm
def resample(image, scan, new_spacing=[1, 1, 1]):
    # Determine current voxel spacing
    spacing = np.array([scan[0].SliceThickness, scan[0].PixelSpacing[0], scan[0].PixelSpacing[1]], dtype=np.float32)

    resize_factor = spacing / new_spacing
    new_real_shape = image.shape * resize_factor
    new_shape = np.round(new_real_shape)
    real_resize_factor = new_shape / image.shape

    image = scipy.ndimage.interpolation.zoom(image, real_resize_factor, mode='nearest')
    image = image.astype(np.float32)

    return image


def soft_dice_loss(y_true, y_pred, epsilon=1e-6):
    numerator = 2. * tf.reduce_sum(y_pred * y_true)
    denominator = tf.reduce_sum(y_pred + y_true)

    return 1 - (numerator / (denominator + epsilon))


def strt_img(request, patient_id, slice):
    predicted = []
    BASE = settings.BASE_DIR
    DICOM = settings.STATICFILES_DIRS[1]

    path = os.path.join(DICOM, str(patient_id))

    scans = load_scan(patient_id)
    imgs_to_process = get_pixels_hu(scans)

    org = np.uint8(cv2.normalize(image_histogram_equalization(imgs_to_process[slice]), None, 0, 255, cv2.NORM_MINMAX))
    original = image_histogram_equalization(imgs_to_process[slice])
    cv2.imwrite(path + '/image_proces/original/' + str(slice) + '.png', original)

    croped_image = crop(imgs_to_process[slice])
    # cv2.imwrite(path + '/image_proces/croped/' + str(slice) + '.png', croped_image)
    # pdb.set_trace()

    enhanced_image = image_histogram_equalization(croped_image)
    # cv2.imwrite(path + '/image_proces/enhanced/' + str(slice) + '.png', croped_image)

    threshold_image = threshold(enhanced_image)
    # cv2.imwrite(path + '/image_proces/threshold/' + str(slice) + '.png', threshold_image)

    eroded_image = erode(threshold_image)
    # cv2.imwrite(path + '/image_proces/eroded/' + str(slice) + '.png', eroded_image)

    largest_shape = countores(eroded_image)
    # cv2.imwrite(path + '/image_proces/largest_shape/' + str(slice) + '.png', largest_shape)

    src2 = make_mask(largest_shape, imgs_to_process)
    # cv2.imwrite(path + '/image_proces/masks/' + str(slice) + '.png', src2)

    # src2 = np.float64(src2)
    src1 = org
    final = segement_liver(src1, src2)
    # cv2.imwrite(path + '/image_proces/segement/' + str(slice) + '.png', final)

    # final = find_tumor(final)
    cv2.imwrite(path + '/image_proces/tumors/' + str(slice) + '.png', final)

    predicted.append(final)
    patient_id = str(patient_id)
    original = 'DICOM/' + patient_id + '/image_proces/original/' + str(slice) + '.png'

    # croped_image = 'DICOM/' + patient_id + '/image_proces/enhanced/' + str(slice) + '.png'
    # pdb.set_trace()
    # enhanced_image = 'DICOM/' + patient_id + '/image_proces/enhanced/' + str(slice) + '.png'
    # threshold_image = 'DICOM/' + patient_id + '/image_proces/threshold/' + str(slice) + '.png'
    # eroded_image = 'DICOM/' + patient_id + '/image_proces/eroded/' + str(slice) + '.png'
    # largest_shape = 'DICOM/' + patient_id + '/image_proces/largest_shape/' + str(slice) + '.png'
    # checked = 'DICOM/' + patient_id + '/image_proces/checked_axis/' + str(slice) + '.png'
    # src2 = 'DICOM/' + patient_id + '/image_proces/masks/' + str(slice) + '.png'
    # final = 'DICOM/' + patient_id + '/image_proces/segement/' + str(slice) + '.png'
    last = 'DICOM/' + patient_id + '/image_proces/tumors/' + str(slice) + '.png'

    paths = [original, last]
    # pdb.set_trace()

    return render(request, 'png.html', {'paths': paths})


def make_DL_folders(path):
    if not os.path.exists(path + '/' + 'DL'):
        os.mkdir(path + '/' + 'DL')
        processed_path = os.path.join(path, 'DL')
        # pdb.set_trace()
        os.mkdir(processed_path + '/' + 'original')
        os.mkdir(processed_path + '/' + 'tumors')
    path = path + '/DL'
    return path


def get_countors(Patient, TumorMasks, LiverMasks):
    '''
  from the segmants output of both networks we get the liver and tumor countors
  apply them to the ptaient
  returns the patient with both iver and tumor contours
  '''
    LiverEdges = np.zeros_like(LiverMasks)
    for i, slice in enumerate(LiverMasks):
        LiverEdges[i] = cv2.Canny(slice, 0, 1).reshape(256, 256, 1)
    TumorEdges = np.zeros_like(TumorMasks)
    for i, slice in enumerate(TumorMasks):
        TumorEdges[i] = cv2.Canny(slice, 0, 1).reshape(256, 256, 1)
    Patient = Patient * 255
    Patient[LiverEdges == 255] = 255
    Patient[TumorEdges == 255] = 0
    return Patient


def start(request, patient_id):
    predicted = []
    # reading data
    DICOM = settings.STATICFILES_DIRS[1]

    # get patient
    patient = Patient.objects.get(id=patient_id)

    # get PATIENT_DICOM of patient
    file = patient.PATIENT_DICOM

    # path of target directory to unzip
    target = os.path.join(DICOM, str(patient.id))

    # unzip directory
    with zipfile.ZipFile(file.path, 'r') as zip:
        path = zip.extractall(target)
    # pdb.set_trace()

    # make dl folders
    path = make_DL_folders(target)

    # pdb.set_trace()
    target = target + "/PATIENT_DICOM"
    slices = [pydicom.read_file(target + "/" + s) for s in os.listdir(target)]
    slices.sort(key=lambda x: int(x.ImagePositionPatient[2]))

    # pdb.set_trace()

    # getting Hounsfield units
    patient_pixels = get_pixels_hu_DL(slices)

    # normalize patiens
    normalized_patient = normalize(patient_pixels)
    pix_resampled = resample(normalized_patient, slices, [1, 1, 1])
    resampled_patient_pixels = pix_resampled

    # resize slices to 256*256
    patient_256 = []
    for j in range(len(resampled_patient_pixels)):
        resized1 = cv2.resize(resampled_patient_pixels[j], (256, 256), interpolation=cv2.INTER_AREA)
        patient_256.append(resized1)
    img_width = 256
    img_hight = 256
    img_channels = 1
    len_in = len(patient_256)

    # stack all slices to be ready for model
    model_in = np.zeros((len_in, img_hight, img_width, img_channels), dtype=np.float32)
    for j, each_slice in enumerate(patient_256):
        model_in[j] = patient_256[j].reshape((256, 256, 1))
    layer = tf.keras.layers
    inputs = layer.Input((img_width, img_hight, img_channels))
    c1 = layer.Conv2D(16, (3, 3), activation='relu', kernel_initializer='he_normal', padding='same')(inputs)
    c1 = layer.Dropout(0.1)(c1)
    c1 = layer.Conv2D(16, (3, 3), activation='relu', kernel_initializer='he_normal', padding='same')(c1)
    p1 = layer.AveragePooling2D((2, 2))(c1)
    c2 = layer.Conv2D(32, (3, 3), activation='relu', kernel_initializer='he_normal', padding='same')(p1)
    c2 = layer.Dropout(0.1)(c2)
    c2 = layer.Conv2D(32, (3, 3), activation='relu', kernel_initializer='he_normal', padding='same')(c2)
    p2 = layer.AveragePooling2D((2, 2))(c2)
    c3 = layer.Conv2D(64, (3, 3), activation='relu', kernel_initializer='he_normal', padding='same')(p2)
    c3 = layer.Dropout(0.2)(c3)
    c3 = layer.Conv2D(64, (3, 3), activation='relu', kernel_initializer='he_normal', padding='same')(c3)
    p3 = layer.AveragePooling2D((2, 2))(c3)
    c4 = layer.Conv2D(128, (3, 3), activation='relu', kernel_initializer='he_normal', padding='same')(p3)
    c4 = layer.Dropout(0.2)(c4)
    c4 = layer.Conv2D(128, (3, 3), activation='relu', kernel_initializer='he_normal', padding='same')(c4)
    p4 = layer.AveragePooling2D((2, 2))(c4)
    c5 = layer.Conv2D(256, (3, 3), activation='relu', kernel_initializer='he_normal', padding='same')(p4)
    c5 = layer.Dropout(0.3)(c5)
    c5 = layer.Conv2D(256, (3, 3), activation='relu', kernel_initializer='he_normal', padding='same')(c5)
    # Decoders
    u6 = layer.Conv2DTranspose(128, (2, 2), strides=(2, 2), padding='same')(c5)
    u6 = layer.concatenate([u6, c4])
    c6 = layer.Conv2D(128, (3, 3), activation='relu', kernel_initializer='he_normal', padding='same')(u6)
    c6 = layer.Dropout(0.2)(c6)
    c6 = layer.Conv2D(128, (3, 3), activation='relu', kernel_initializer='he_normal', padding='same')(c6)
    u7 = layer.Conv2DTranspose(64, (2, 2), strides=(2, 2), padding='valid')(c6)
    u7 = layer.concatenate([u7, c3])
    c7 = layer.Conv2D(64, (3, 3), activation='relu', kernel_initializer='he_normal', padding='same')(u7)
    c7 = layer.Dropout(0.2)(c7)
    c7 = layer.Conv2D(64, (3, 3), activation='relu', kernel_initializer='he_normal', padding='same')(c7)
    u8 = layer.Conv2DTranspose(32, (2, 2), strides=(2, 2), padding='valid')(c7)
    u8 = layer.concatenate([u8, c2])
    c8 = layer.Conv2D(32, (3, 3), activation='relu', kernel_initializer='he_normal', padding='same')(u8)
    c8 = layer.Dropout(0.1)(c8)
    c8 = layer.Conv2D(32, (3, 3), activation='relu', kernel_initializer='he_normal', padding='same')(c8)
    u9 = layer.Conv2DTranspose(16, (2, 2), strides=(2, 2), padding='valid')(c8)
    u9 = layer.concatenate([u9, c1], axis=3)
    c9 = layer.Conv2D(16, (3, 3), activation='relu', kernel_initializer='he_normal', padding='same')(u9)
    u9 = layer.Dropout(0.1)(c9)
    c9 = layer.Conv2D(16, (3, 3), activation='relu', kernel_initializer='he_normal', padding='same')(c9)
    outputs = layer.Conv2D(1, (1, 1), activation='sigmoid')(c9)
    model = tf.keras.Model(inputs=[inputs], outputs=[outputs])
    model.compile(optimizer='adam', loss=soft_dice_loss,
                  metrics=[tf.keras.metrics.MeanIoU(num_classes=2, name='Mean_IoU')])
    model.summary()
    # Tumor Model Weights

    deep_model_file = DeepModel.objects.all().last()
    # model.load_weights('/home/shaker/model-direct-tumor.h5')
    model.load_weights(deep_model_file.tumor_file.path)

    # model
    predicted = model.predict(model_in)
    predicted = (predicted > 0.5).astype(np.uint8)
    #########################################################################
    # Liver Model Weights
    deep_model_file = DeepModel.objects.all().last()
    model.load_weights(deep_model_file.model_file.path)

    # segamted outtput
    predicted2 = model.predict(model_in)
    predicted2 = (predicted2 > 0.5).astype(np.uint8)

    # coutoured output
    predicted = get_countors(model_in, predicted, predicted2)

    #########################################################################
    # predicted = [slice.reshape((256, 256)) for slice in predicted]
    # model_in = [slice.reshape((256, 256)) for slice in model_in]
    tumor_index = []
    cancered = False
    for i in range(len(predicted) - 1):
        if 1 not in predicted[i] and 1 in predicted[i + 1]:
            tumor_index.append(i + 1)
            cancered = True

    print_out = "Tumors detected at srarting indexes "
    for index in tumor_index:
        print_out = print_out + " " + str(index)
    if cancered:
        sent = print_out
    else:
        sent = 'patient have no tumor'
    # predicted = reverse_resample(predicted, slices)
    # model_in = reverse_resample(model_in, slices)


    for img_indx in range(len(predicted) - 1):
        m = predicted[img_indx].reshape(256, 256)
        tumor_mask = np.uint8(cv2.normalize(m, None, 0, 255, cv2.NORM_MINMAX))

        n = model_in[img_indx].reshape(256, 256)
        patient_mask = np.uint8(cv2.normalize(n, None, 0, 255, cv2.NORM_MINMAX))

        cv2.imwrite(path + '/original/' + str(img_indx) + '.png', cv2.cvtColor(patient_mask, cv2.COLOR_GRAY2RGB))
        cv2.imwrite(path + '/tumors/' + str(img_indx) + '.png', cv2.cvtColor(tumor_mask, cv2.COLOR_GRAY2RGB))
    #pdb.set_trace()
    return redirect('deepmodel:get_slice_dl',
                    patient_id=patient_id,
                    slices_num=len(predicted),
                    message=sent)


def reverse_resample(image, scan, new_spacing=[1, 1, 1]):
    # Determine current pixel spacing
    spacing = map(float, ([scan[0].SliceThickness] + list(scan[0].PixelSpacing)))
    spacing = np.array(list(spacing))
    resize_factor = spacing * new_spacing
    new_real_shape = image.shape * resize_factor
    new_shape = new_real_shape
    real_resize_factor = image.shape / new_shape
    new_spacing = spacing / real_resize_factor
    image = scipy.ndimage.interpolation.zoom(image, real_resize_factor)
    return image, new_spacing
